"""phase 5 storyboards and animatic

Revision ID: 202607160005
Revises: 202607160004
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607160005"
down_revision: str | None = "202607160004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storyboard_frames",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("shot_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("frame_number", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("narration_text", sa.Text(), nullable=False),
        sa.Column("dialogue_text", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_storyboard_frames_project_id"),
        "storyboard_frames",
        ["project_id"],
    )
    op.create_index(op.f("ix_storyboard_frames_shot_id"), "storyboard_frames", ["shot_id"])

    op.create_table(
        "audio_tracks",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("track_type", sa.String(length=80), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("alignment", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audio_tracks_project_id"), "audio_tracks", ["project_id"])

    op.create_table(
        "animatics",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("audio_track_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["audio_track_id"], ["audio_tracks.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_animatics_project_id"), "animatics", ["project_id"])

    op.create_table(
        "timelines",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("animatic_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["animatic_id"], ["animatics.id"]),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_timelines_project_id"), "timelines", ["project_id"])

    op.create_table(
        "timeline_items",
        sa.Column("timeline_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=True),
        sa.Column("layer", sa.String(length=80), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["source_asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["timeline_id"], ["timelines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_timeline_items_project_id"), "timeline_items", ["project_id"])
    op.create_index(
        op.f("ix_timeline_items_timeline_id"),
        "timeline_items",
        ["timeline_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_timeline_items_timeline_id"), table_name="timeline_items")
    op.drop_index(op.f("ix_timeline_items_project_id"), table_name="timeline_items")
    op.drop_table("timeline_items")
    op.drop_index(op.f("ix_timelines_project_id"), table_name="timelines")
    op.drop_table("timelines")
    op.drop_index(op.f("ix_animatics_project_id"), table_name="animatics")
    op.drop_table("animatics")
    op.drop_index(op.f("ix_audio_tracks_project_id"), table_name="audio_tracks")
    op.drop_table("audio_tracks")
    op.drop_index(op.f("ix_storyboard_frames_shot_id"), table_name="storyboard_frames")
    op.drop_index(op.f("ix_storyboard_frames_project_id"), table_name="storyboard_frames")
    op.drop_table("storyboard_frames")
