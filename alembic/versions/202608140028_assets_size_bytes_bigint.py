"""change assets.size_bytes from Integer to BigInteger

The ``size_bytes`` column was ``sa.Integer()`` (32-bit, max ~2.1 GB).
With ``max_generated_asset_bytes`` at 750 MB this is borderline for video
assets. This migration upgrades it to ``BigInteger`` (64-bit) to safely
accommodate large generated files.

Also adds a server_default of 0 to avoid NULL ambiguity for existing rows
that were never reconciled.

Revision ID: 202608140028
Revises: 202608140027
Create Date: 2026-08-14
"""

import sqlalchemy as sa

from alembic import op

revision = "202608140028"
down_revision = "202608140027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "assets",
        "size_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "assets",
        "size_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )