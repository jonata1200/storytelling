"""Add the soft-delete timestamp missing from QA results.

Revision ID: 202608270036
Revises: 202608260035
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608270036"
down_revision: str | None = "202608260035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "qa_results",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("qa_results", "deleted_at")
