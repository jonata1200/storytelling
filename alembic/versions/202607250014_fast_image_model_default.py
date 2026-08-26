"""fast image model default

Revision ID: 202607250014
Revises: 202607220013
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607250014"
down_revision: str | None = "202607220013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FAST_IMAGE_MODEL = "sourceful/riverflow-v2-fast"
LEGACY_IMAGE_MODEL = "sourceful/riverflow-v2.5-pro"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE project_production_settings
            SET image_model = :fast_model
            WHERE image_model = :legacy_model
            """
        ).bindparams(fast_model=FAST_IMAGE_MODEL, legacy_model=LEGACY_IMAGE_MODEL)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE project_production_settings
            SET image_model = :legacy_model
            WHERE image_model = :fast_model
            """
        ).bindparams(fast_model=FAST_IMAGE_MODEL, legacy_model=LEGACY_IMAGE_MODEL)
    )
