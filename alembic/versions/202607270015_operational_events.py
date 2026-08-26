"""operational events

Revision ID: 202607270015
Revises: 202607250014
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607270015"
down_revision: str | None = "202607250014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operational_events",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=True),
        sa.Column("provider", sa.String(length=120), nullable=True),
        sa.Column("model", sa.String(length=180), nullable=True),
        sa.Column("operation", sa.String(length=120), nullable=True),
        sa.Column("correlation_id", sa.String(length=120), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(12, 6), nullable=True),
        sa.Column("actual_cost", sa.Numeric(12, 6), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["generation_jobs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_operational_events_project_id"), "operational_events", ["project_id"])
    op.create_index(op.f("ix_operational_events_event_type"), "operational_events", ["event_type"])
    op.create_index(op.f("ix_operational_events_status"), "operational_events", ["status"])
    op.create_index(
        op.f("ix_operational_events_correlation_id"),
        "operational_events",
        ["correlation_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_operational_events_correlation_id"), table_name="operational_events")
    op.drop_index(op.f("ix_operational_events_status"), table_name="operational_events")
    op.drop_index(op.f("ix_operational_events_event_type"), table_name="operational_events")
    op.drop_index(op.f("ix_operational_events_project_id"), table_name="operational_events")
    op.drop_table("operational_events")
