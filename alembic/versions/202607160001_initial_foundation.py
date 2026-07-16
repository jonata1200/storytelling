"""initial foundation

Revision ID: 202607160001
Revises:
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607160001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    project_status = sa.Enum(
        "DRAFT",
        "IDEA_GENERATION",
        "IDEA_APPROVAL",
        "STORY_DESIGN",
        "STORY_APPROVAL",
        "SCRIPT_GENERATION",
        "SCRIPT_APPROVAL",
        "VISUAL_BIBLE_GENERATION",
        "VISUAL_BIBLE_APPROVAL",
        "STORYBOARD_GENERATION",
        "STORYBOARD_APPROVAL",
        "PRODUCTION_PLANNING",
        "VIDEO_GENERATION",
        "VIDEO_REVIEW",
        "AUDIO_GENERATION",
        "ASSEMBLY",
        "QUALITY_CONTROL",
        "FINAL_APPROVAL",
        "COMPLETED",
        "FAILED",
        "ARCHIVED",
        name="project_status",
    )
    artifact_status = sa.Enum(
        "PENDING",
        "GENERATING",
        "READY_FOR_REVIEW",
        "APPROVED",
        "REJECTED",
        "STALE",
        "FAILED",
        "CANCELLED",
        name="artifact_status",
    )
    artifact_type = sa.Enum(
        "BRIEFING",
        "STORY_IDEA",
        "STORY_BIBLE",
        "SCRIPT",
        "CHARACTER",
        "LOCATION",
        "PROP",
        "SCENE",
        "SHOT",
        "STORYBOARD",
        "ANIMATIC",
        "VIDEO_CLIP",
        "AUDIO_TRACK",
        "TIMELINE",
        "EXPORT",
        name="artifact_type",
    )
    approval_decision = sa.Enum(
        "APPROVED",
        "REJECTED",
        "CHANGES_REQUESTED",
        "BLOCKED",
        name="approval_decision",
    )

    project_status.create(op.get_bind())
    artifact_status.create(op.get_bind())
    artifact_type.create(op.get_bind())
    approval_decision.create(op.get_bind())

    op.create_table(
        "users",
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "workspaces",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "projects",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", project_status, nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "project_versions",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_project_versions_project_id"), "project_versions", ["project_id"], unique=False
    )

    op.create_table(
        "artifacts",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", artifact_type, nullable=False),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("status", artifact_status, nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_artifacts_project_id"), "artifacts", ["project_id"], unique=False)

    op.create_table(
        "artifact_versions",
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prompt_execution_id", sa.Uuid(), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_artifact_versions_artifact_id"),
        "artifact_versions",
        ["artifact_id"],
        unique=False,
    )

    op.create_table(
        "approvals",
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_version_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=True),
        sa.Column("decision", approval_decision, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["artifact_version_id"], ["artifact_versions.id"]),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approvals_artifact_id"), "approvals", ["artifact_id"], unique=False)
    op.create_index(
        op.f("ix_approvals_artifact_version_id"),
        "approvals",
        ["artifact_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_approvals_artifact_version_id"), table_name="approvals")
    op.drop_index(op.f("ix_approvals_artifact_id"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(op.f("ix_artifact_versions_artifact_id"), table_name="artifact_versions")
    op.drop_table("artifact_versions")
    op.drop_index(op.f("ix_artifacts_project_id"), table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index(op.f("ix_project_versions_project_id"), table_name="project_versions")
    op.drop_table("project_versions")
    op.drop_table("projects")
    op.drop_table("workspaces")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    sa.Enum(name="approval_decision").drop(op.get_bind())
    sa.Enum(name="artifact_type").drop(op.get_bind())
    sa.Enum(name="artifact_status").drop(op.get_bind())
    sa.Enum(name="project_status").drop(op.get_bind())
