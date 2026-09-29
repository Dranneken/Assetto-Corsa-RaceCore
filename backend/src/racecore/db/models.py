"""Initial durable race records; live high-frequency telemetry stays in RAM."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from racecore.db.base import Base

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class Driver(Base):
    __tablename__ = "drivers"

    driver_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_state_created", "state", "created_at"),)

    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    track_id: Mapped[str] = mapped_column(String(128), nullable=False)
    track_layout: Mapped[str | None] = mapped_column(String(128))
    session_type: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pre_race")
    paused_from_state: Mapped[str | None] = mapped_column(String(24))
    planned_laps: Mapped[int | None] = mapped_column(Integer)
    planned_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionEntry(Base):
    __tablename__ = "session_entries"
    __table_args__ = (
        UniqueConstraint("session_id", "car_id", name="uq_session_entries_session_car"),
        Index("ix_session_entries_session_position", "session_id", "position"),
    )

    entry_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    driver_id: Mapped[str] = mapped_column(ForeignKey("drivers.driver_id"), nullable=False)
    car_id: Mapped[str] = mapped_column(String(64), nullable=False)
    car_model: Mapped[str] = mapped_column(String(128), nullable=False)
    class_name: Mapped[str | None] = mapped_column(String(64))
    team_name: Mapped[str | None] = mapped_column(String(128))
    position: Mapped[int | None] = mapped_column(Integer)
    class_position: Mapped[int | None] = mapped_column(Integer)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Result(Base):
    __tablename__ = "results"
    __table_args__ = (
        UniqueConstraint("session_id", "entry_id", name="uq_results_session_entry"),
        CheckConstraint("laps_completed >= 0", name="results_laps_nonnegative"),
    )

    result_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    entry_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("session_entries.entry_id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int | None] = mapped_column(Integer)
    class_position: Mapped[int | None] = mapped_column(Integer)
    laps_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_time_seconds: Mapped[float | None] = mapped_column(Numeric(12, 3))
    best_lap_seconds: Mapped[float | None] = mapped_column(Numeric(10, 3))
    fastest_sectors: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False)


class Lap(Base):
    __tablename__ = "laps"
    __table_args__ = (
        UniqueConstraint("entry_id", "lap_number", name="uq_laps_entry_lap_number"),
        CheckConstraint("lap_number > 0", name="laps_number_positive"),
        CheckConstraint("lap_time_seconds > 0", name="laps_time_positive"),
        Index("ix_laps_session_lap", "session_id", "lap_number"),
    )

    lap_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    entry_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("session_entries.entry_id", ondelete="CASCADE"), nullable=False
    )
    lap_number: Mapped[int] = mapped_column(Integer, nullable=False)
    lap_time_seconds: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    sector_times: Mapped[list[float]] = mapped_column(JSON_DOCUMENT, nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incidents_session_status", "session_id", "status"),)

    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    incident_type: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="detected")
    track_location: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    evidence_uri: Mapped[str | None] = mapped_column(Text)
    steward_notes: Mapped[str | None] = mapped_column(Text)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IncidentParticipant(Base):
    __tablename__ = "incident_participants"

    incident_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("incidents.incident_id", ondelete="CASCADE"), primary_key=True
    )
    entry_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("session_entries.entry_id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str | None] = mapped_column(String(32))


class Penalty(Base):
    __tablename__ = "penalties"

    penalty_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    incident_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("incidents.incident_id", ondelete="SET NULL")
    )
    entry_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("session_entries.entry_id", ondelete="CASCADE"), nullable=False
    )
    penalty_type: Mapped[str] = mapped_column(String(48), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    issued_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StewardReview(Base):
    __tablename__ = "steward_reviews"
    __table_args__ = (Index("ix_steward_reviews_incident_created", "incident_id", "created_at"),)

    review_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    incident_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False
    )
    steward_id: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_session_time", "session_id", "occurred_at"),)

    audit_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sessions.session_id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(96), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    details: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
