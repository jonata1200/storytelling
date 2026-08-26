"""ensure story idea long text columns

Revision ID: 202607220013
Revises: 202607210012
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607220013"
down_revision: str | None = "202607210012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("story_ideas") as batch_op:
        batch_op.alter_column(
            "hook",
            existing_type=sa.String(length=220),
            type_=sa.Text(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "premise",
            existing_type=sa.String(length=220),
            type_=sa.Text(),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("story_ideas") as batch_op:
        batch_op.alter_column(
            "hook",
            existing_type=sa.Text(),
            type_=sa.String(length=220),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "premise",
            existing_type=sa.Text(),
            type_=sa.String(length=220),
            existing_nullable=False,
        )
