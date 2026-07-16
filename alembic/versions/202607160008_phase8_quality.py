"""phase 8 quality

Revision ID: 202607160008
Revises: 202607160007
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607160008"
down_revision: str | None = "202607160007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "continuity_states",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("shot_id", sa.Uuid(), nullable=True),
        sa.Column("storyboard_frame_id", sa.Uuid(), nullable=True),
        sa.Column("timeline_item_id", sa.Uuid(), nullable=True),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("previous_state_id", sa.Uuid(), nullable=True),
        sa.Column("scene_number", sa.Integer(), nullable=True),
        sa.Column("shot_number", sa.Integer(), nullable=True),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["previous_state_id"], ["continuity_states.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"]),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["storyboard_frame_id"], ["storyboard_frames.id"]),
        sa.ForeignKeyConstraint(["timeline_item_id"], ["timeline_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_continuity_states_project_id"), "continuity_states", ["project_id"])
    op.create_index(op.f("ix_continuity_states_shot_id"), "continuity_states", ["shot_id"])

    op.create_table(
        "continuity_issues",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("continuity_state_id", sa.Uuid(), nullable=True),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("issue_code", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("expected", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actual", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("accepted_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["continuity_state_id"], ["continuity_states.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_continuity_issues_project_id"), "continuity_issues", ["project_id"])
    op.create_index(
        op.f("ix_continuity_issues_continuity_state_id"),
        "continuity_issues",
        ["continuity_state_id"],
    )

    op.create_table(
        "quality_checks",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("target_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("check_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["target_artifact_id"], ["artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quality_checks_project_id"), "quality_checks", ["project_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_quality_checks_project_id"), table_name="quality_checks")
    op.drop_table("quality_checks")
    op.drop_index(
        op.f("ix_continuity_issues_continuity_state_id"),
        table_name="continuity_issues",
    )
    op.drop_index(op.f("ix_continuity_issues_project_id"), table_name="continuity_issues")
    op.drop_table("continuity_issues")
    op.drop_index(op.f("ix_continuity_states_shot_id"), table_name="continuity_states")
    op.drop_index(op.f("ix_continuity_states_project_id"), table_name="continuity_states")
    op.drop_table("continuity_states")
