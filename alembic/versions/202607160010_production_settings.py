"""production settings

Revision ID: 202607160010
Revises: 202607160008
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607160010"
down_revision: str | None = "202607160008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_production_settings",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("parent_project_id", sa.Uuid(), nullable=True),
        sa.Column("episode_number", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("aspect_ratio", sa.String(length=20), nullable=False),
        sa.Column("image_resolution", sa.String(length=40), nullable=False),
        sa.Column("video_resolution", sa.String(length=40), nullable=False),
        sa.Column("workflow_mode", sa.String(length=80), nullable=False),
        sa.Column(
            "image_model",
            sa.String(length=160),
            server_default="gemini-3.1-flash-lite-image",
            nullable=False,
        ),
        sa.Column(
            "video_model",
            sa.String(length=160),
            server_default="veo-3.1-lite-generate-preview",
            nullable=False,
        ),
        sa.Column("audio_mode", sa.String(length=80), nullable=False),
        sa.Column("motion_intensity", sa.Integer(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["parent_project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_project_production_settings_project_id"),
    )
    op.create_index(
        op.f("ix_project_production_settings_project_id"),
        "project_production_settings",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_project_production_settings_project_id"),
        table_name="project_production_settings",
    )
    op.drop_table("project_production_settings")
