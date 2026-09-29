"""HTTP request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from racecore.domain.sessions import (
    AuditEvent,
    CarRaceState,
    ConnectionStatus,
    DriverStatus,
    PitStatus,
    SessionCommand,
    SessionConfiguration,
    SessionState,
)


class CreateSessionRequest(BaseModel):
    config: SessionConfiguration


class CommandRequest(BaseModel):
    command: SessionCommand


class CarStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_lap: int | None = None
    position: int | None = None
    class_position: int | None = None
    sector: int | None = None
    sector_times: list[float] | None = None
    lap_times: list[float] | None = None
    gap_to_ahead_seconds: float | None = None
    gap_to_leader_seconds: float | None = None
    pit_status: PitStatus | None = None
    driver_status: DriverStatus | None = None
    connection_status: ConnectionStatus | None = None
    retired: bool | None = None
    damage_percent: float | None = None


class SessionResponse(BaseModel):
    session_id: UUID
    config: SessionConfiguration
    state: SessionState
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    paused_from_state: SessionState | None
    car_states: dict[str, CarRaceState]
    audit_events: list[AuditEvent]

    @classmethod
    def from_session(cls, session: Any) -> SessionResponse:
        return cls.model_validate(session.model_dump())


class RaceStateResponse(BaseModel):
    session_id: UUID
    session_state: SessionState
    updated_at: datetime
    leaderboard: list[CarRaceState]


class CommandResponse(BaseModel):
    session: SessionResponse
    event: AuditEvent
