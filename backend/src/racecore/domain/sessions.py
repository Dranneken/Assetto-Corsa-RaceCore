"""Session configuration, state transitions, and in-memory race state."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class SessionType(StrEnum):
    PRACTICE = "practice"
    QUALIFYING = "qualifying"
    RACE = "race"
    ENDURANCE = "endurance"


class SessionState(StrEnum):
    PRE_RACE = "pre_race"
    FORMATION = "formation"
    GREEN = "green"
    YELLOW = "yellow"
    SAFETY_CAR = "safety_car"
    RED_FLAG = "red_flag"
    PAUSED = "paused"
    FINISHED = "finished"
    POST_RACE = "post_race"


class SessionCommand(StrEnum):
    START = "start"
    GREEN = "green"
    YELLOW = "yellow"
    SAFETY_CAR = "safety_car"
    RED_FLAG = "red_flag"
    RESUME = "resume"
    PAUSE = "pause"
    RESTART = "restart"
    FINISH = "finish"
    POST_RACE = "post_race"
    RESET = "reset"


class PitStatus(StrEnum):
    ON_TRACK = "on_track"
    PIT_ENTRY = "pit_entry"
    PIT_LANE = "pit_lane"
    PIT_BOX = "pit_box"
    PIT_EXIT = "pit_exit"


class DriverStatus(StrEnum):
    ACTIVE = "active"
    DISCONNECTED = "disconnected"
    RETIRED = "retired"
    FINISHED = "finished"


class ConnectionStatus(StrEnum):
    CONNECTED = "connected"
    STALE = "stale"
    DISCONNECTED = "disconnected"


class SessionEntry(BaseModel):
    """A configured car and driver participating in a session."""

    model_config = ConfigDict(extra="forbid")

    car_id: str = Field(min_length=1, max_length=64)
    driver_id: str = Field(min_length=1, max_length=128)
    driver_name: str = Field(min_length=1, max_length=128)
    car_model: str = Field(min_length=1, max_length=128)
    class_name: str | None = Field(default=None, max_length=64)
    team_name: str | None = Field(default=None, max_length=128)


class SessionConfiguration(BaseModel):
    """Validated configuration snapshot stored with the created session."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    track_id: str = Field(min_length=1, max_length=128)
    track_layout: str | None = Field(default=None, max_length=128)
    session_type: SessionType = SessionType.RACE
    planned_laps: int | None = Field(default=None, gt=0)
    planned_duration_seconds: int | None = Field(default=None, gt=0)
    entries: list[SessionEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_car_ids(self) -> SessionConfiguration:
        car_ids = [entry.car_id for entry in self.entries]
        if len(car_ids) != len(set(car_ids)):
            raise ValueError("Each session entry must use a unique car_id")
        return self


class CarRaceState(BaseModel):
    """Latest authoritative, low-rate state for one entered car."""

    car_id: str
    driver_id: str
    driver_name: str
    car_model: str
    class_name: str | None = None
    team_name: str | None = None
    current_lap: int = Field(default=0, ge=0)
    position: int | None = Field(default=None, ge=1)
    class_position: int | None = Field(default=None, ge=1)
    sector: int | None = Field(default=None, ge=1, le=3)
    sector_times: list[float] = Field(default_factory=list)
    lap_times: list[float] = Field(default_factory=list)
    lap_history_complete: bool = True
    speed_kmh: float | None = Field(default=None, ge=0)
    rpm: int | None = Field(default=None, ge=0)
    gear: int | None = None
    throttle: float | None = Field(default=None, ge=0, le=1)
    brake: float | None = Field(default=None, ge=0, le=1)
    steering: float | None = Field(default=None, ge=-1, le=1)
    fuel_liters: float | None = Field(default=None, ge=0)
    tyre_temperatures_c: list[float] = Field(default_factory=list)
    tyre_pressures_psi: list[float] = Field(default_factory=list)
    track_position: float | None = Field(default=None, ge=0, le=1)
    track_length_m: float | None = Field(default=None, gt=0)
    position_xyz: list[float] | None = None
    damage_state: dict[str, float] = Field(default_factory=dict)
    car_state: str = "unknown"
    gap_to_ahead_seconds: float | None = None
    gap_to_leader_seconds: float | None = None
    pit_status: PitStatus = PitStatus.ON_TRACK
    driver_status: DriverStatus = DriverStatus.ACTIVE
    connection_status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    retired: bool = False
    damage_percent: float | None = Field(default=None, ge=0, le=100)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("sector_times", "lap_times")
    @classmethod
    def times_must_be_positive(cls, values: list[float]) -> list[float]:
        if any(value <= 0 for value in values):
            raise ValueError("Lap and sector times must be positive")
        return values


class AuditEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    event_type: str
    timestamp: datetime = Field(default_factory=utc_now)
    actor: str
    details: dict[str, Any] = Field(default_factory=dict)


class InvalidSessionCommand(ValueError):
    """Raised when a command is not valid for the current session state."""


class RaceSession(BaseModel):
    """In-memory session aggregate; mutations are performed by RaceCoreStore."""

    model_config = ConfigDict(validate_assignment=True)

    session_id: UUID = Field(default_factory=uuid4)
    config: SessionConfiguration
    state: SessionState = SessionState.PRE_RACE
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    paused_from_state: SessionState | None = None
    car_states: dict[str, CarRaceState] = Field(default_factory=dict)
    audit_events: list[AuditEvent] = Field(default_factory=list)

    def add_event(
        self,
        event_type: str,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            session_id=self.session_id,
            event_type=event_type,
            actor=actor,
            details=details or {},
        )
        self.audit_events.append(event)
        return event

    def apply_command(self, command: SessionCommand, actor: str) -> AuditEvent:
        before = self.state
        now = utc_now()

        if command is SessionCommand.START and self.state is SessionState.PRE_RACE:
            self.state = SessionState.FORMATION
            self.started_at = now
        elif command is SessionCommand.GREEN and self.state is SessionState.FORMATION:
            self.state = SessionState.GREEN
        elif command is SessionCommand.YELLOW and self.state is SessionState.GREEN:
            self.state = SessionState.YELLOW
        elif command is SessionCommand.SAFETY_CAR and self.state in {
            SessionState.GREEN,
            SessionState.YELLOW,
        }:
            self.state = SessionState.SAFETY_CAR
        elif command is SessionCommand.RED_FLAG and self.state in {
            SessionState.FORMATION,
            SessionState.GREEN,
            SessionState.YELLOW,
            SessionState.SAFETY_CAR,
        }:
            self.state = SessionState.RED_FLAG
        elif command is SessionCommand.PAUSE and self.state in {
            SessionState.PRE_RACE,
            SessionState.FORMATION,
            SessionState.GREEN,
            SessionState.YELLOW,
            SessionState.SAFETY_CAR,
            SessionState.RED_FLAG,
        }:
            self.paused_from_state = self.state
            self.state = SessionState.PAUSED
        elif command is SessionCommand.RESUME and self.state is SessionState.PAUSED:
            self.state = self.paused_from_state or SessionState.PRE_RACE
            self.paused_from_state = None
        elif command is SessionCommand.RESUME and self.state in {
            SessionState.YELLOW,
            SessionState.SAFETY_CAR,
        }:
            self.state = SessionState.GREEN
        elif command is SessionCommand.RESUME and self.state is SessionState.RED_FLAG:
            self.state = SessionState.FORMATION
        elif command is SessionCommand.RESTART and self.state in {
            SessionState.FORMATION,
            SessionState.GREEN,
            SessionState.YELLOW,
            SessionState.SAFETY_CAR,
            SessionState.RED_FLAG,
            SessionState.FINISHED,
        }:
            self.state = SessionState.FORMATION
            self.started_at = now
            self.finished_at = None
            self.paused_from_state = None
            self._reset_car_states()
        elif command is SessionCommand.FINISH and self.state in {
            SessionState.FORMATION,
            SessionState.GREEN,
            SessionState.YELLOW,
            SessionState.SAFETY_CAR,
            SessionState.RED_FLAG,
        }:
            self.state = SessionState.FINISHED
            self.finished_at = now
        elif command is SessionCommand.POST_RACE and self.state is SessionState.FINISHED:
            self.state = SessionState.POST_RACE
        elif command is SessionCommand.RESET and self.state is not SessionState.POST_RACE:
            self.state = SessionState.PRE_RACE
            self.started_at = None
            self.finished_at = None
            self.paused_from_state = None
            self._reset_car_states()
        else:
            raise InvalidSessionCommand(
                f"Command '{command.value}' is not valid while session state is '{self.state.value}'"
            )

        return self.add_event(
            f"session.command.{command.value}",
            actor,
            {"from_state": before.value, "to_state": self.state.value},
        )

    def update_car_state(self, car_id: str, values: dict[str, Any]) -> CarRaceState:
        if car_id not in self.car_states:
            raise KeyError(car_id)
        current = self.car_states[car_id]
        updated = CarRaceState.model_validate(
            {**current.model_dump(), **values, "updated_at": utc_now()}
        )
        self.car_states[car_id] = updated
        return updated

    def leaderboard(self) -> list[CarRaceState]:
        return sorted(
            self.car_states.values(),
            key=lambda car: (
                car.position is None,
                car.position if car.position is not None else 2**31,
                car.car_id,
            ),
        )

    def apply_live_telemetry(self, car_id: str, values: dict[str, Any]) -> CarRaceState:
        """Update volatile race state without performing per-packet database writes."""
        return self.update_car_state(car_id, values)

    def _reset_car_states(self) -> None:
        self.car_states = {
            entry.car_id: CarRaceState(
                car_id=entry.car_id,
                driver_id=entry.driver_id,
                driver_name=entry.driver_name,
                car_model=entry.car_model,
                class_name=entry.class_name,
                team_name=entry.team_name,
            )
            for entry in self.config.entries
        }
