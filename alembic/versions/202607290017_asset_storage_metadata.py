"""Add asset storage metadata.

Revision ID: 202607290017
Revises: 202607290016
Create Date: 2026-07-29 09:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607290017"
down_revision: str | None = "202607290016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("size_bytes", sa.Integer(), nullable=True))
    op.add_column("assets", sa.Column("missing_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "assets",
        sa.Column("storage_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_assets_size_bytes", "assets", ["size_bytes"])
    op.create_index("ix_assets_missing_at", "assets", ["missing_at"])


def downgrade() -> None:
    op.drop_index("ix_assets_missing_at", table_name="assets")
    op.drop_index("ix_assets_size_bytes", table_name="assets")
    op.drop_column("assets", "storage_checked_at")
    op.drop_column("assets", "missing_at")
    op.drop_column("assets", "size_bytes")
