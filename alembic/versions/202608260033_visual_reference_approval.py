"""Add relational approval state to visual references.

Revision ID: 202608260033
Revises: 202608230032
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608260033"
down_revision: str | None = "202608230032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "visual_references",
        sa.Column("status", sa.String(length=24), server_default="generated", nullable=False),
    )
    op.add_column(
        "visual_references",
        sa.Column("is_canonical", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(
        "ix_visual_references_status", "visual_references", ["status"], unique=False
    )
    op.create_index(
        "ix_visual_references_is_canonical",
        "visual_references",
        ["is_canonical"],
        unique=False,
    )
    op.create_index(
        "uq_visual_reference_canonical_target",
        "visual_references",
        ["target_kind", "target_id"],
        unique=True,
        postgresql_where=sa.text("is_canonical"),
    )


def downgrade() -> None:
    op.drop_index("uq_visual_reference_canonical_target", table_name="visual_references")
    op.drop_index("ix_visual_references_is_canonical", table_name="visual_references")
    op.drop_index("ix_visual_references_status", table_name="visual_references")
    op.drop_column("visual_references", "is_canonical")
    op.drop_column("visual_references", "status")
