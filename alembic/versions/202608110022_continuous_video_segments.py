"""continuous video segments

Revision ID: 202608110022
Revises: 202608080021
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202608110022"
down_revision: str | None = "202608080021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


generation_job_status = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    "RETRY_SCHEDULED",
    name="generation_job_status",
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "continuous_video_plans",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=80), nullable=False),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("segment_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("segment_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_continuous_video_plans_project_id"),
    )
    op.create_index(
        op.f("ix_continuous_video_plans_project_id"),
        "continuous_video_plans",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_continuous_video_plans_status"),
        "continuous_video_plans",
        ["status"],
        unique=False,
    )
    op.create_table(
        "continuous_video_segments",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("segment_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("status", generation_job_status, nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("generation_job_id", sa.Uuid(), nullable=True),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("source_segment_id", sa.Uuid(), nullable=True),
        sa.Column("source_video_asset_id", sa.Uuid(), nullable=True),
        sa.Column("external_operation_id", sa.String(length=220), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("cost_estimate", sa.Numeric(12, 6), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(
            ["generation_job_id"],
            ["generation_jobs.id"],
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_segment_id"], ["continuous_video_segments.id"]),
        sa.ForeignKeyConstraint(["source_video_asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "segment_number",
            name="uq_continuous_video_segments_project_segment",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_continuous_video_segments_idempotency_key",
        ),
    )
    op.create_index(
        op.f("ix_continuous_video_segments_external_operation_id"),
        "continuous_video_segments",
        ["external_operation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_continuous_video_segments_generation_job_id"),
        "continuous_video_segments",
        ["generation_job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_continuous_video_segments_project_id"),
        "continuous_video_segments",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_continuous_video_segments_project_status",
        "continuous_video_segments",
        ["project_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_continuous_video_segments_request_fingerprint"),
        "continuous_video_segments",
        ["request_fingerprint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_continuous_video_segments_status"),
        "continuous_video_segments",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_continuous_video_segments_status"),
        table_name="continuous_video_segments",
    )
    op.drop_index(
        op.f("ix_continuous_video_segments_request_fingerprint"),
        table_name="continuous_video_segments",
    )
    op.drop_index(
        "ix_continuous_video_segments_project_status",
        table_name="continuous_video_segments",
    )
    op.drop_index(
        op.f("ix_continuous_video_segments_project_id"),
        table_name="continuous_video_segments",
    )
    op.drop_index(
        op.f("ix_continuous_video_segments_generation_job_id"),
        table_name="continuous_video_segments",
    )
    op.drop_index(
        op.f("ix_continuous_video_segments_external_operation_id"),
        table_name="continuous_video_segments",
    )
    op.drop_table("continuous_video_segments")
    op.drop_index(op.f("ix_continuous_video_plans_status"), table_name="continuous_video_plans")
    op.drop_index(
        op.f("ix_continuous_video_plans_project_id"),
        table_name="continuous_video_plans",
    )
    op.drop_table("continuous_video_plans")
