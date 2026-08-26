"""Remove obsolete AI image-generation project settings.

Revision ID: 202608230032
Revises: 202608200031
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608230032"
down_revision: str | None = "202608200031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("project_production_settings", "image_model")
    op.drop_column("project_production_settings", "image_resolution")


def downgrade() -> None:
    op.add_column(
        "project_production_settings",
        sa.Column(
            "image_resolution",
            sa.String(length=40),
            server_default="720x1280",
            nullable=False,
        ),
    )
    op.add_column(
        "project_production_settings",
        sa.Column(
            "image_model",
            sa.String(length=160),
            server_default="sourceful/riverflow-v2.5-fast",
            nullable=False,
        ),
    )
