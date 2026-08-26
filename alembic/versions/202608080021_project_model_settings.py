"""project model settings

Revision ID: 202608080021
Revises: 202608050020
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202608080021"
down_revision: str | None = "202608050020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_model_settings",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("task", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=220), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "task",
            name="uq_project_model_settings_project_task",
        ),
    )
    op.create_index(
        op.f("ix_project_model_settings_project_id"),
        "project_model_settings",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_model_settings_task"),
        "project_model_settings",
        ["task"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_project_model_settings_task"), table_name="project_model_settings")
    op.drop_index(
        op.f("ix_project_model_settings_project_id"),
        table_name="project_model_settings",
    )
    op.drop_table("project_model_settings")
