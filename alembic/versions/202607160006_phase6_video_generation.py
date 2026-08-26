"""phase 6 video generation

Revision ID: 202607160006
Revises: 202607160005
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607160006"
down_revision: str | None = "202607160005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    generation_job_type = postgresql.ENUM(
        "IMAGE",
        "VIDEO",
        "SPEECH",
        "RENDER",
        "ANALYSIS",
        name="generation_job_type",
        create_type=False,
    )
    clip_review_decision = postgresql.ENUM(
        "APPROVED",
        "REJECTED",
        "NEEDS_REGENERATION",
        name="clip_review_decision",
        create_type=False,
    )
    generation_job_status.create(op.get_bind(), checkfirst=True)
    generation_job_type.create(op.get_bind(), checkfirst=True)
    clip_review_decision.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "generation_jobs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("result_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("external_job_id", sa.String(length=220), nullable=True),
        sa.Column("job_type", generation_job_type, nullable=False),
        sa.Column("status", generation_job_status, nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cost_estimate", sa.Numeric(12, 6), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["result_artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        op.f("ix_generation_jobs_external_job_id"),
        "generation_jobs",
        ["external_job_id"],
    )
    op.create_index(
        op.f("ix_generation_jobs_project_id"),
        "generation_jobs",
        ["project_id"],
    )

    op.create_table(
        "video_clips",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("storyboard_frame_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("generation_job_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("variant_index", sa.Integer(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["generation_job_id"], ["generation_jobs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["storyboard_frame_id"], ["storyboard_frames.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_video_clips_generation_job_id"), "video_clips", ["generation_job_id"])
    op.create_index(op.f("ix_video_clips_project_id"), "video_clips", ["project_id"])
    op.create_index(
        op.f("ix_video_clips_storyboard_frame_id"),
        "video_clips",
        ["storyboard_frame_id"],
    )

    op.create_table(
        "clip_reviews",
        sa.Column("video_clip_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=True),
        sa.Column("decision", clip_review_decision, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["video_clip_id"], ["video_clips.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("clip_reviews")
    op.drop_index(op.f("ix_video_clips_storyboard_frame_id"), table_name="video_clips")
    op.drop_index(op.f("ix_video_clips_project_id"), table_name="video_clips")
    op.drop_index(op.f("ix_video_clips_generation_job_id"), table_name="video_clips")
    op.drop_table("video_clips")
    op.drop_index(op.f("ix_generation_jobs_project_id"), table_name="generation_jobs")
    op.drop_index(op.f("ix_generation_jobs_external_job_id"), table_name="generation_jobs")
    op.drop_table("generation_jobs")
    postgresql.ENUM(name="clip_review_decision").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="generation_job_type").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="generation_job_status").drop(op.get_bind(), checkfirst=True)
