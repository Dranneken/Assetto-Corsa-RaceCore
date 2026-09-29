"""Thread-safe session store with optional PostgreSQL durability."""

from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as DatabaseSession
from sqlalchemy.orm import sessionmaker

from racecore.config import settings
from racecore.db.models import (
    AuditLog,
    Driver,
    Lap,
    Result,
    SessionEntry,
    SessionRecord,
)
from racecore.domain.sessions import (
    AuditEvent,
    CarRaceState,
    ConnectionStatus,
    DriverStatus,
    PitStatus,
    RaceSession,
    SessionCommand,
    SessionConfiguration,
    SessionState,
    utc_now,
)
from racecore.domain.telemetry import TelemetryPacket


class RaceCoreStore:
    """Own active race state in RAM and persist durable records when configured."""

    def __init__(self, database_url: str | None = None) -> None:
        self._sessions: dict[UUID, RaceSession] = {}
        self._lock = RLock()
        self._engine: Engine | None = (
            create_engine(database_url, pool_pre_ping=True) if database_url else None
        )
        self._session_factory: sessionmaker[DatabaseSession] | None = (
            sessionmaker(self._engine, expire_on_commit=False) if self._engine else None
        )

    @property
    def persistence_enabled(self) -> bool:
        return self._session_factory is not None

    def initialize(self) -> None:
        """Load durable sessions after the database has been migrated."""
        if self._session_factory is None:
            return

        with self._lock, self._session_factory() as db:
            records = db.scalars(select(SessionRecord).order_by(SessionRecord.created_at)).all()
            for record in records:
                config = SessionConfiguration.model_validate(record.config_snapshot)
                session = RaceSession(
                    session_id=record.session_id,
                    config=config,
                    state=SessionState(record.state),
                    created_at=record.created_at,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                    paused_from_state=(
                        SessionState(record.paused_from_state) if record.paused_from_state else None
                    ),
                )
                session._reset_car_states()
                entries = db.scalars(
                    select(SessionEntry).where(SessionEntry.session_id == record.session_id)
                ).all()
                for entry in entries:
                    car = session.car_states.get(entry.car_id)
                    if car is None:
                        continue
                    laps = db.scalars(
                        select(Lap).where(Lap.entry_id == entry.entry_id).order_by(Lap.lap_number)
                    ).all()
                    result = db.scalar(
                        select(Result).where(
                            Result.session_id == record.session_id,
                            Result.entry_id == entry.entry_id,
                        )
                    )
                    lap_times = [float(lap.lap_time_seconds) for lap in laps]
                    values: dict[str, Any] = {
                        "lap_times": lap_times,
                        "current_lap": max(
                            len(lap_times), result.laps_completed if result is not None else 0
                        ),
                    }
                    if result is not None:
                        values.update(
                            {
                                "position": result.position,
                                "class_position": result.class_position,
                                "driver_status": result.status,
                                "sector_times": result.fastest_sectors.get("sector_times", []),
                            }
                        )
                    session.update_car_state(entry.car_id, values)
                events = db.scalars(
                    select(AuditLog)
                    .where(AuditLog.session_id == record.session_id)
                    .order_by(AuditLog.occurred_at, AuditLog.audit_id)
                ).all()
                session.audit_events = [
                    AuditEvent(
                        event_id=event.audit_id,
                        session_id=record.session_id,
                        event_type=event.event_type,
                        timestamp=event.occurred_at,
                        actor=event.actor,
                        details=event.details,
                    )
                    for event in events
                ]
                self._sessions[session.session_id] = session

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()

    def create_session(self, config: SessionConfiguration, actor: str) -> RaceSession:
        with self._lock:
            session = RaceSession(config=config)
            session._reset_car_states()
            event = session.add_event("session.created", actor, {"name": config.name})

            if self._session_factory is not None:
                with self._session_factory.begin() as db:
                    db.add(
                        SessionRecord(
                            session_id=session.session_id,
                            name=config.name,
                            track_id=config.track_id,
                            track_layout=config.track_layout,
                            session_type=config.session_type.value,
                            state=session.state.value,
                            paused_from_state=None,
                            planned_laps=config.planned_laps,
                            planned_duration_seconds=config.planned_duration_seconds,
                            config_snapshot=config.model_dump(mode="json"),
                            created_at=session.created_at,
                        )
                    )
                    for entry in config.entries:
                        driver = db.get(Driver, entry.driver_id)
                        if driver is None:
                            db.add(
                                Driver(driver_id=entry.driver_id, display_name=entry.driver_name)
                            )
                        elif driver.display_name != entry.driver_name:
                            driver.display_name = entry.driver_name
                    db.flush()
                    db.add_all(
                        [
                            SessionEntry(
                                session_id=session.session_id,
                                driver_id=entry.driver_id,
                                car_id=entry.car_id,
                                car_model=entry.car_model,
                                class_name=entry.class_name,
                                team_name=entry.team_name,
                            )
                            for entry in config.entries
                        ]
                    )
                    self._save_audit_event(db, event)

            self._sessions[session.session_id] = session
            return session.model_copy(deep=True)

    def list_sessions(self) -> list[RaceSession]:
        with self._lock:
            return [session.model_copy(deep=True) for session in self._sessions.values()]

    def get_session(self, session_id: UUID) -> RaceSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            return session.model_copy(deep=True) if session else None

    def command(
        self,
        session_id: UUID,
        command: SessionCommand,
        actor: str,
    ) -> tuple[RaceSession | None, AuditEvent | None]:
        with self._lock:
            current = self._sessions.get(session_id)
            if current is None:
                return None, None

            candidate = current.model_copy(deep=True)
            event = candidate.apply_command(command, actor)
            if self._session_factory is not None:
                with self._session_factory.begin() as db:
                    record = db.get(SessionRecord, session_id)
                    if record is None:
                        raise RuntimeError(f"Session {session_id} is missing from PostgreSQL")
                    record.state = candidate.state.value
                    record.paused_from_state = (
                        candidate.paused_from_state.value if candidate.paused_from_state else None
                    )
                    record.started_at = candidate.started_at
                    record.finished_at = candidate.finished_at
                    if command in {SessionCommand.RESTART, SessionCommand.RESET}:
                        db.execute(delete(Result).where(Result.session_id == session_id))
                        db.execute(delete(Lap).where(Lap.session_id == session_id))
                    if command is SessionCommand.FINISH:
                        self._save_results(db, candidate)
                    self._save_audit_event(db, event)

            self._sessions[session_id] = candidate
            return candidate.model_copy(deep=True), event.model_copy(deep=True)

    def update_car_state(
        self,
        session_id: UUID,
        car_id: str,
        values: dict[str, Any],
        actor: str,
    ) -> tuple[RaceSession | None, CarRaceState | None, None]:
        del actor  # Live state updates are transient and are not durable audit events.
        with self._lock:
            current = self._sessions.get(session_id)
            if current is None:
                return None, None, None

            candidate = current.model_copy(deep=True)
            try:
                car = candidate.update_car_state(car_id, values)
            except KeyError:
                return candidate.model_copy(deep=True), None, None

            if self._session_factory is not None:
                with self._session_factory.begin() as db:
                    record = db.get(SessionRecord, session_id)
                    if record is None:
                        raise RuntimeError(f"Session {session_id} is missing from PostgreSQL")
                    entry = db.scalar(
                        select(SessionEntry).where(
                            SessionEntry.session_id == session_id,
                            SessionEntry.car_id == car_id,
                        )
                    )
                    if entry is None:
                        raise RuntimeError(
                            f"Configured car {car_id} is missing from PostgreSQL session {session_id}"
                        )
                    self._save_completed_laps(db, session_id, entry.entry_id, car)

            self._sessions[session_id] = candidate
            return candidate.model_copy(deep=True), car.model_copy(deep=True), None

    def apply_live_telemetry(
        self,
        session_id: UUID,
        packet: TelemetryPacket,
    ) -> RaceSession | None:
        """Update the RAM-only timing view and derive field order from track progress."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or packet.car_id not in session.car_states:
                return None
            entry = next(
                item for item in session.config.entries if item.car_id == packet.car_id
            )
            if entry.driver_id != packet.driver_id:
                raise ValueError("Telemetry driver does not match the configured session entry")
            previous_pit_status = session.car_states[packet.car_id].pit_status
            pit_status = packet.pit_status
            if previous_pit_status is PitStatus.ON_TRACK and pit_status is PitStatus.PIT_LANE:
                pit_status = PitStatus.PIT_ENTRY
            elif previous_pit_status in {PitStatus.PIT_LANE, PitStatus.PIT_BOX} and pit_status is PitStatus.ON_TRACK:
                pit_status = PitStatus.PIT_EXIT

            session.apply_live_telemetry(
                packet.car_id,
                {
                    "current_lap": packet.current_lap,
                    "sector": packet.sector,
                    "sector_times": packet.sector_times,
                    "lap_times": packet.lap_times,
                    "lap_history_complete": packet.lap_history_complete,
                    "speed_kmh": packet.speed_kmh,
                    "rpm": packet.rpm,
                    "gear": packet.gear,
                    "throttle": packet.throttle,
                    "brake": packet.brake,
                    "steering": packet.steering,
                    "fuel_liters": packet.fuel_liters,
                    "tyre_temperatures_c": packet.tyre_temperatures_c,
                    "tyre_pressures_psi": packet.tyre_pressures_psi,
                    "track_position": packet.track_position,
                    "track_length_m": packet.track_length_m,
                    "position_xyz": packet.position_xyz,
                    "pit_status": pit_status,
                    "damage_percent": packet.damage_percent,
                    "damage_state": packet.damage_state,
                    "car_state": packet.car_state,
                    "driver_status": DriverStatus.RETIRED if packet.retired else DriverStatus.ACTIVE,
                    "connection_status": ConnectionStatus.CONNECTED,
                    "retired": packet.retired,
                },
            )

            car_state = session.car_states[packet.car_id]
            if packet.completed_lap_time_seconds is not None and self._session_factory is not None:
                with self._session_factory.begin() as db:
                    entry_id = self._entry_id(db, session_id, packet.car_id)
                    self._save_telemetry_lap(
                        db,
                        session_id,
                        entry_id,
                        packet.current_lap,
                        packet.completed_lap_time_seconds,
                        packet.completed_lap_sector_times,
                        packet.completed_lap_valid,
                        car_state.updated_at,
                    )

            ordered = sorted(
                session.car_states.values(),
                key=lambda car: (
                    car.track_position is None,
                    -(
                        car.current_lap + (car.track_position or 0)
                        if car.track_position is not None
                        else 0
                    ),
                    car.car_id,
                ),
            )
            observed = [car for car in ordered if car.track_position is not None]
            leader = observed[0] if observed else None
            for overall_position, car in enumerate(observed, start=1):
                same_class = [item for item in observed if item.class_name == car.class_name]
                class_position = same_class.index(car) + 1
                ahead = observed[overall_position - 2] if overall_position > 1 else None
                progress = car.current_lap + (car.track_position or 0)
                track_length_m = car.track_length_m or packet.track_length_m
                car.position = overall_position
                car.class_position = class_position
                car.gap_to_leader_seconds = (
                    max(
                        0.0,
                        (
                            (leader.current_lap + (leader.track_position or 0))
                            - progress
                        )
                        * (track_length_m or 0)
                        / max(((car.speed_kmh or 0) + (leader.speed_kmh or 0)) / 7.2, 1.0),
                    )
                    if leader is not None and track_length_m
                    else None
                )
                car.gap_to_ahead_seconds = (
                    max(
                        0.0,
                        (
                            (ahead.current_lap + (ahead.track_position or 0))
                            - progress
                        )
                        * (track_length_m or 0)
                        / max(((car.speed_kmh or 0) + (ahead.speed_kmh or 0)) / 7.2, 1.0),
                    )
                    if ahead is not None and track_length_m
                    else None
                )
            for car in session.car_states.values():
                if car.track_position is None:
                    car.position = None
                    car.class_position = None
                    car.gap_to_ahead_seconds = None
                    car.gap_to_leader_seconds = None
            return session.model_copy(deep=True)

    def set_connection_status(
        self,
        session_id: UUID,
        car_id: str,
        status: ConnectionStatus,
    ) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or car_id not in session.car_states:
                return
            car = session.car_states[car_id]
            if car.connection_status is not status:
                car.connection_status = status
                if status is ConnectionStatus.DISCONNECTED and car.driver_status is DriverStatus.ACTIVE:
                    car.driver_status = DriverStatus.DISCONNECTED
                car.updated_at = utc_now()

    @staticmethod
    def _save_audit_event(db: DatabaseSession, event: AuditEvent) -> None:
        db.add(
            AuditLog(
                audit_id=event.event_id,
                session_id=event.session_id,
                event_type=event.event_type,
                actor=event.actor,
                occurred_at=event.timestamp,
                details=event.details,
            )
        )

    @staticmethod
    def _save_completed_laps(
        db: DatabaseSession,
        session_id: UUID,
        entry_id: UUID,
        car: CarRaceState,
    ) -> None:
        if not car.lap_times:
            return
        existing = {
            lap.lap_number: lap
            for lap in db.scalars(select(Lap).where(Lap.entry_id == entry_id)).all()
        }
        for lap_number, lap_time in enumerate(car.lap_times, start=1):
            if lap_number > car.current_lap:
                break
            lap = existing.get(lap_number)
            if lap is None:
                db.add(
                    Lap(
                        session_id=session_id,
                        entry_id=entry_id,
                        lap_number=lap_number,
                        lap_time_seconds=lap_time,
                        sector_times=(
                            list(car.sector_times) if lap_number == car.current_lap else []
                        ),
                        is_valid=True,
                        completed_at=car.updated_at,
                    )
                )
            elif float(lap.lap_time_seconds) != lap_time:
                lap.lap_time_seconds = lap_time
                lap.completed_at = car.updated_at
            if lap is not None and lap_number == car.current_lap:
                lap.sector_times = list(car.sector_times)

    @staticmethod
    def _save_telemetry_lap(
        db: DatabaseSession,
        session_id: UUID,
        entry_id: UUID,
        lap_number: int,
        lap_time_seconds: float,
        sector_times: list[float],
        is_valid: bool,
        completed_at: datetime,
    ) -> None:
        lap = db.scalar(
            select(Lap).where(Lap.entry_id == entry_id, Lap.lap_number == lap_number)
        )
        if lap is None:
            db.add(
                Lap(
                    session_id=session_id,
                    entry_id=entry_id,
                    lap_number=lap_number,
                    lap_time_seconds=lap_time_seconds,
                    sector_times=sector_times,
                    is_valid=is_valid,
                    completed_at=completed_at,
                )
            )
        else:
            lap.lap_time_seconds = lap_time_seconds
            lap.sector_times = sector_times
            lap.is_valid = is_valid
            lap.completed_at = completed_at

    @staticmethod
    def _save_results(db: DatabaseSession, session: RaceSession) -> None:
        for entry in session.config.entries:
            car = session.car_states[entry.car_id]
            lap_times = car.lap_times[: car.current_lap] if car.lap_history_complete else []
            db.add(
                Result(
                    session_id=session.session_id,
                    entry_id=RaceCoreStore._entry_id(db, session.session_id, entry.car_id),
                    position=car.position,
                    class_position=car.class_position,
                    laps_completed=car.current_lap,
                    total_time_seconds=sum(lap_times) if lap_times else None,
                    best_lap_seconds=min(lap_times) if lap_times else None,
                    fastest_sectors={
                        "sector_times": car.sector_times if car.lap_history_complete else []
                    },
                    status=car.driver_status.value,
                )
            )

    @staticmethod
    def _entry_id(db: DatabaseSession, session_id: UUID, car_id: str) -> UUID:
        entry_id = db.scalar(
            select(SessionEntry.entry_id).where(
                SessionEntry.session_id == session_id,
                SessionEntry.car_id == car_id,
            )
        )
        if entry_id is None:
            raise RuntimeError(
                f"Configured car {car_id} is missing from PostgreSQL session {session_id}"
            )
        return entry_id


store = RaceCoreStore(database_url=settings.database_url)
