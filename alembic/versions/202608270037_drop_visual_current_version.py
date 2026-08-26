"""Drop the orphan current_version column from character and location tables.

The character_versions/location_versions tables were dropped in
202608200031, so current_version on characters/locations is now orphaned
and was removed from the ORM models.

Revision ID: 202608270037
Revises: 202608270036
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608270037"
down_revision: str | None = "202608270036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("characters", "current_version")
    op.drop_column("locations", "current_version")


def downgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "locations",
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
    )
