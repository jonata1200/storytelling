"""dubbing jobs

Revision ID: 202607310018
Revises: 202607290017
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607310018"
down_revision: str | None = "202607290017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dubbing_jobs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("export_id", sa.Uuid(), nullable=False),
        sa.Column("result_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("result_asset_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("external_job_id", sa.String(length=220), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("source_language", sa.String(length=16), nullable=True),
        sa.Column("target_language", sa.String(length=16), nullable=False),
        sa.Column("result_uri", sa.String(length=1024), nullable=True),
        sa.Column("cost_estimate", sa.Numeric(12, 6), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["export_id"], ["exports.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["result_artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["result_asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dubbing_jobs_external_job_id"), "dubbing_jobs", ["external_job_id"])
    op.create_index(op.f("ix_dubbing_jobs_export_id"), "dubbing_jobs", ["export_id"])
    op.create_index(op.f("ix_dubbing_jobs_project_id"), "dubbing_jobs", ["project_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_dubbing_jobs_project_id"), table_name="dubbing_jobs")
    op.drop_index(op.f("ix_dubbing_jobs_export_id"), table_name="dubbing_jobs")
    op.drop_index(op.f("ix_dubbing_jobs_external_job_id"), table_name="dubbing_jobs")
    op.drop_table("dubbing_jobs")
