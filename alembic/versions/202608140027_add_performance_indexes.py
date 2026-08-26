"""add performance indexes on generation_jobs and operational_events

Adds missing indexes for common query patterns:
- generation_jobs(status, updated_at): used by list_stale_pending_jobs / list_stale_running_jobs
- operational_events(job_id): used by job-related event lookups
- operational_events(created_at): used by time-ordered event queries

Revision ID: 202608140027
Revises: 202608130026
Create Date: 2026-08-14
"""

from alembic import op

revision = "202608140027"
down_revision = "202608130026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_generation_jobs_status_updated_at",
        "generation_jobs",
        ["status", "updated_at"],
    )
    op.create_index(
        "ix_operational_events_job_id",
        "operational_events",
        ["job_id"],
    )
    op.create_index(
        "ix_operational_events_created_at",
        "operational_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_operational_events_created_at", table_name="operational_events")
    op.drop_index("ix_operational_events_job_id", table_name="operational_events")
    op.drop_index("ix_generation_jobs_status_updated_at", table_name="generation_jobs")