"""Create initial durable race schema.

Revision ID: 0001_initial
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "drivers",
        sa.Column("driver_id", sa.String(128), primary_key=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("track_id", sa.String(128), nullable=False),
        sa.Column("track_layout", sa.String(128)),
        sa.Column("session_type", sa.String(24), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("paused_from_state", sa.String(24)),
        sa.Column("planned_laps", sa.Integer()),
        sa.Column("planned_duration_seconds", sa.Integer()),
        sa.Column("config_snapshot", JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_sessions_state_created", "sessions", ["state", "created_at"])
    op.create_table(
        "session_entries",
        sa.Column("entry_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.Uuid(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("driver_id", sa.String(128), sa.ForeignKey("drivers.driver_id"), nullable=False),
        sa.Column("car_id", sa.String(64), nullable=False),
        sa.Column("car_model", sa.String(128), nullable=False),
        sa.Column("class_name", sa.String(64)),
        sa.Column("team_name", sa.String(128)),
        sa.Column("position", sa.Integer()),
        sa.Column("class_position", sa.Integer()),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("session_id", "car_id", name="uq_session_entries_session_car"),
    )
    op.create_index("ix_session_entries_session_position", "session_entries", ["session_id", "position"])
    op.create_table(
        "results",
        sa.Column("result_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.Uuid(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_id", sa.Uuid(as_uuid=True), sa.ForeignKey("session_entries.entry_id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer()),
        sa.Column("class_position", sa.Integer()),
        sa.Column("laps_completed", sa.Integer(), nullable=False),
        sa.Column("total_time_seconds", sa.Numeric(12, 3)),
        sa.Column("best_lap_seconds", sa.Numeric(10, 3)),
        sa.Column("fastest_sectors", JSON_DOCUMENT, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.CheckConstraint("laps_completed >= 0", name="results_laps_nonnegative"),
        sa.UniqueConstraint("session_id", "entry_id", name="uq_results_session_entry"),
    )
    op.create_table(
        "laps",
        sa.Column("lap_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.Uuid(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_id", sa.Uuid(as_uuid=True), sa.ForeignKey("session_entries.entry_id", ondelete="CASCADE"), nullable=False),
        sa.Column("lap_number", sa.Integer(), nullable=False),
        sa.Column("lap_time_seconds", sa.Numeric(10, 3), nullable=False),
        sa.Column("sector_times", JSON_DOCUMENT, nullable=False),
        sa.Column("is_valid", sa.Boolean(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("lap_number > 0", name="laps_number_positive"),
        sa.CheckConstraint("lap_time_seconds > 0", name="laps_time_positive"),
        sa.UniqueConstraint("entry_id", "lap_number", name="uq_laps_entry_lap_number"),
    )
    op.create_index("ix_laps_session_lap", "laps", ["session_id", "lap_number"])
    op.create_table(
        "incidents",
        sa.Column("incident_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.Uuid(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("incident_type", sa.String(48), nullable=False),
        sa.Column("severity", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("track_location", JSON_DOCUMENT),
        sa.Column("evidence_uri", sa.Text()),
        sa.Column("steward_notes", sa.Text()),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_incidents_session_status", "incidents", ["session_id", "status"])
    op.create_table(
        "incident_participants",
        sa.Column("incident_id", sa.Uuid(as_uuid=True), sa.ForeignKey("incidents.incident_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("entry_id", sa.Uuid(as_uuid=True), sa.ForeignKey("session_entries.entry_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(32)),
    )
    op.create_table(
        "penalties",
        sa.Column("penalty_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.Uuid(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("incident_id", sa.Uuid(as_uuid=True), sa.ForeignKey("incidents.incident_id", ondelete="SET NULL")),
        sa.Column("entry_id", sa.Uuid(as_uuid=True), sa.ForeignKey("session_entries.entry_id", ondelete="CASCADE"), nullable=False),
        sa.Column("penalty_type", sa.String(48), nullable=False),
        sa.Column("details", JSON_DOCUMENT, nullable=False),
        sa.Column("issued_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "steward_reviews",
        sa.Column("review_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("incident_id", sa.Uuid(as_uuid=True), sa.ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False),
        sa.Column("steward_id", sa.String(128), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_steward_reviews_incident_created", "steward_reviews", ["incident_id", "created_at"])
    op.create_table(
        "audit_logs",
        sa.Column("audit_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.Uuid(as_uuid=True), sa.ForeignKey("sessions.session_id", ondelete="SET NULL")),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("details", JSON_DOCUMENT, nullable=False),
    )
    op.create_index("ix_audit_logs_session_time", "audit_logs", ["session_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_session_time", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_steward_reviews_incident_created", table_name="steward_reviews")
    op.drop_table("steward_reviews")
    op.drop_table("penalties")
    op.drop_table("incident_participants")
    op.drop_index("ix_incidents_session_status", table_name="incidents")
    op.drop_table("incidents")
    op.drop_index("ix_laps_session_lap", table_name="laps")
    op.drop_table("laps")
    op.drop_table("results")
    op.drop_index("ix_session_entries_session_position", table_name="session_entries")
    op.drop_table("session_entries")
    op.drop_index("ix_sessions_state_created", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("drivers")
