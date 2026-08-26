"""continuous video default workflow

Revision ID: 202608110025
Revises: 202608110024
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608110025"
down_revision: str | None = "202608110024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE project_production_settings AS settings
        SET workflow_mode = 'continuous_fast'
        WHERE settings.workflow_mode IS NULL
           OR btrim(settings.workflow_mode) = ''
           OR (
                settings.workflow_mode = 'keyframes_i2v'
                AND NOT EXISTS (
                    SELECT 1
                    FROM storyboard_frames AS frames
                    WHERE frames.project_id = settings.project_id
                )
           )
        """
    )
    op.alter_column(
        "project_production_settings",
        "workflow_mode",
        existing_type=sa.String(length=80),
        nullable=False,
        server_default="continuous_fast",
    )


def downgrade() -> None:
    op.alter_column(
        "project_production_settings",
        "workflow_mode",
        existing_type=sa.String(length=80),
        nullable=False,
        server_default="keyframes_i2v",
    )
