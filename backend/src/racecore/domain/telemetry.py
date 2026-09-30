"""Validated live telemetry packets and bounded in-memory collection."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime
from math import floor, isfinite
from threading import RLock
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from racecore.domain.sessions import PitStatus


class TelemetryPacket(BaseModel):
    """One client sample. Sequence numbers are monotonic per session and car."""

    model_config = ConfigDict(extra="forbid")

    car_id: str = Field(min_length=1, max_length=64)
    driver_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=0)
    speed_kmh: float = Field(ge=0, le=1000, allow_inf_nan=False)
    rpm: int = Field(ge=0, le=100_000)
    gear: int = Field(ge=-1, le=20)
    throttle: float = Field(ge=0, le=1, allow_inf_nan=False)
    brake: float = Field(ge=0, le=1, allow_inf_nan=False)
    steering: float = Field(ge=-1, le=1, allow_inf_nan=False)
    fuel_liters: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    tyre_temperatures_c: list[float] = Field(default_factory=list, max_length=4)
    tyre_pressures_psi: list[float] = Field(default_factory=list, max_length=4)
    current_lap: int = Field(default=0, ge=0)
    sector: int | None = Field(default=None, ge=1, le=3)
    sector_times: list[float] = Field(default_factory=list, max_length=3)
    lap_times: list[float] = Field(default_factory=list, max_length=100_000)
    lap_history_complete: bool = True
    completed_lap_time_seconds: float | None = Field(
        default=None, gt=0, le=3600, allow_inf_nan=False
    )
    completed_lap_sector_times: list[float] = Field(default_factory=list, max_length=3)
    completed_lap_valid: bool = True
    track_position: float = Field(ge=0, le=1, allow_inf_nan=False)
    track_length_m: float | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)
    position_xyz: list[float] = Field(min_length=3, max_length=3)
    pit_status: PitStatus = PitStatus.ON_TRACK
    damage_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    damage_state: dict[str, float] = Field(default_factory=dict)
    retired: bool = False
    car_state: str = Field(default="unknown", max_length=32)
    client_round_trip_ms: float | None = Field(default=None, ge=0, le=60_000, allow_inf_nan=False)
    sampled_at: datetime | None = None

    @field_validator("sector_times", "lap_times", "completed_lap_sector_times")
    @classmethod
    def lap_times_must_be_positive(cls, values: list[float]) -> list[float]:
        if any(not isfinite(value) or value <= 0 for value in values):
            raise ValueError("Lap and sector times must be positive")
        return values

    @field_validator("tyre_temperatures_c")
    @classmethod
    def tyre_temperatures_must_be_finite(cls, values: list[float]) -> list[float]:
        if any(not isfinite(value) or not -100 <= value <= 1000 for value in values):
            raise ValueError("Tyre temperatures are outside the supported range")
        return values

    @field_validator("tyre_pressures_psi")
    @classmethod
    def tyre_pressures_must_be_finite(cls, values: list[float]) -> list[float]:
        if any(not isfinite(value) or not 0 <= value <= 1000 for value in values):
            raise ValueError("Tyre pressures are outside the supported range")
        return values

    @field_validator("position_xyz")
    @classmethod
    def coordinates_must_be_finite(cls, values: list[float]) -> list[float]:
        if any(not isfinite(value) or not -1_000_000 <= value <= 1_000_000 for value in values):
            raise ValueError("Position coordinates are outside the supported range")
        return values

    @field_validator("damage_state")
    @classmethod
    def damage_values_must_be_finite(cls, values: dict[str, float]) -> dict[str, float]:
        if any(not isfinite(value) or not 0 <= value <= 1000 for value in values.values()):
            raise ValueError("Damage readings are outside the supported range")
        return values


class ReceivedTelemetry(BaseModel):
    packet: TelemetryPacket
    received_at: datetime


class CarTelemetryHealth(BaseModel):
    car_id: str
    driver_id: str
    connection_status: str
    latest_sequence: int | None = None
    packets_received: int = 0
    packets_dropped: int = 0
    packets_out_of_order: int = 0
    client_round_trip_ms: float | None = None
    last_packet_at: datetime | None = None
    age_seconds: float | None = None


class TelemetryCollector:
    """Per-session latest samples, health counters, and bounded evidence history."""

    def __init__(self, history_limit: int = 256, stale_after_seconds: float = 1.5):
        self._lock = RLock()
        self._history_limit = history_limit
        self._stale_after_seconds = stale_after_seconds
        self._latest: dict[tuple[UUID, str], ReceivedTelemetry] = {}
        self._history: dict[tuple[UUID, str], deque[ReceivedTelemetry]] = defaultdict(
            lambda: deque(maxlen=self._history_limit)
        )
        self._counts: dict[tuple[UUID, str], dict[str, int]] = defaultdict(
            lambda: {"received": 0, "dropped": 0, "out_of_order": 0}
        )

    def record(self, session_id: UUID, packet: TelemetryPacket) -> ReceivedTelemetry:
        key = (session_id, packet.car_id)
        received_at = datetime.now(UTC)
        received = ReceivedTelemetry(packet=packet, received_at=received_at)
        with self._lock:
            previous = self._latest.get(key)
            counters = self._counts[key]
            if previous is not None:
                if packet.sequence <= previous.packet.sequence:
                    counters["out_of_order"] += 1
                    raise ValueError("Telemetry sequence must increase for each car")
                counters["dropped"] += max(0, packet.sequence - previous.packet.sequence - 1)
            counters["received"] += 1
            self._latest[key] = received
            self._history[key].append(received)
        return received

    def latest(self, session_id: UUID, car_id: str) -> ReceivedTelemetry | None:
        with self._lock:
            return self._latest.get((session_id, car_id))

    def history(self, session_id: UUID, car_id: str, limit: int) -> list[ReceivedTelemetry]:
        with self._lock:
            samples = self._history.get((session_id, car_id), ())
            return list(samples)[-limit:]

    def interpolate(
        self, session_id: UUID, car_id: str, at: datetime
    ) -> ReceivedTelemetry | None:
        """Interpolate continuous values at a time bracketed by buffered samples."""
        with self._lock:
            samples = tuple(self._history.get((session_id, car_id), ()))

        if not samples:
            return None
        if at.tzinfo is None:
            raise ValueError("Interpolation time must include a timezone")
        at = at.astimezone(UTC)

        before = next(
            (sample for sample in reversed(samples) if sample.received_at <= at), None
        )
        after = next((sample for sample in samples if sample.received_at >= at), None)
        if before is None or after is None:
            return None
        if before.received_at == after.received_at:
            return before

        left = before.packet
        right = after.packet
        ratio = (at - before.received_at).total_seconds() / (
            after.received_at - before.received_at
        ).total_seconds()

        def linear(a: float, b: float) -> float:
            return a + (b - a) * ratio

        values: dict[str, object] = {}
        for field in (
            "speed_kmh",
            "throttle",
            "brake",
            "steering",
            "fuel_liters",
            "track_length_m",
            "damage_percent",
        ):
            a, b = getattr(left, field), getattr(right, field)
            if a is not None and b is not None:
                values[field] = linear(a, b)

        for field in ("tyre_temperatures_c", "tyre_pressures_psi", "position_xyz"):
            a, b = getattr(left, field), getattr(right, field)
            if len(a) == len(b):
                values[field] = [linear(x, y) for x, y in zip(a, b)]

        # Interpolate normalized progress across the finish line without moving
        # backwards around the track (for example, 0.99 to 0.01).
        progress_left = left.current_lap + left.track_position
        progress_right = right.current_lap + right.track_position
        values["current_lap"] = floor(linear(progress_left, progress_right))
        values["track_position"] = linear(progress_left, progress_right) % 1.0
        values["sampled_at"] = at

        packet = left.model_copy(update=values)
        return ReceivedTelemetry(packet=packet, received_at=at)

    def health(self, session_id: UUID, car_ids: list[str]) -> list[CarTelemetryHealth]:
        now = datetime.now(UTC)
        results = []
        with self._lock:
            for car_id in car_ids:
                key = (session_id, car_id)
                latest = self._latest.get(key)
                counts = self._counts.get(key, {})
                age = (now - latest.received_at).total_seconds() if latest else None
                connection_status = (
                    "disconnected"
                    if age is None or age >= self._stale_after_seconds * 3
                    else "stale"
                    if age >= self._stale_after_seconds
                    else "connected"
                )
                results.append(
                    CarTelemetryHealth(
                        car_id=car_id,
                        driver_id=latest.packet.driver_id if latest else "",
                        connection_status=connection_status,
                        latest_sequence=latest.packet.sequence if latest else None,
                        packets_received=counts.get("received", 0),
                        packets_dropped=counts.get("dropped", 0),
                        packets_out_of_order=counts.get("out_of_order", 0),
                        client_round_trip_ms=(
                            latest.packet.client_round_trip_ms if latest else None
                        ),
                        last_packet_at=latest.received_at if latest else None,
                        age_seconds=round(age, 3) if age is not None else None,
                    )
                )
        return results


telemetry_collector = TelemetryCollector()
