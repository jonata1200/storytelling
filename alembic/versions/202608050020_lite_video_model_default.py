"""manual video package default

Revision ID: 202608050020
Revises: 202608040019
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608050020"
down_revision: str | None = "202608040019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_MODEL = "manual_package"
NEW_MODEL = "manual_package"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE project_production_settings
            SET video_model = :new_model
            WHERE video_model = :old_model
            """
        ).bindparams(old_model=OLD_MODEL, new_model=NEW_MODEL)
    )
    op.alter_column(
        "project_production_settings",
        "video_model",
        server_default=NEW_MODEL,
        existing_type=sa.String(length=160),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE project_production_settings
            SET video_model = :old_model
            WHERE video_model = :new_model
            """
        ).bindparams(old_model=OLD_MODEL, new_model=NEW_MODEL)
    )
    op.alter_column(
        "project_production_settings",
        "video_model",
        server_default=OLD_MODEL,
        existing_type=sa.String(length=160),
        existing_nullable=False,
    )
