"""add story_hook to scripts

Persists the hook chosen by the user before script generation so the
choice is traceable and reusable.

Revision ID: 202608170029
Revises: 202608140028
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202608170029"
down_revision = "202608140028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scripts",
        sa.Column(
            "story_hook",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("scripts", "story_hook")
