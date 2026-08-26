"""image and video resolution policy

Revision ID: 202608040019
Revises: 202607310018
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608040019"
down_revision: str | None = "202607310018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE project_production_settings
            SET
                aspect_ratio = CASE
                    WHEN aspect_ratio = '16:9'
                        OR image_resolution IN ('1920x1080', '1280x720')
                    THEN '16:9'
                    ELSE '9:16'
                END,
                image_resolution = CASE
                    WHEN aspect_ratio = '16:9'
                        OR image_resolution IN ('1920x1080', '1280x720')
                    THEN '1280x720'
                    ELSE '720x1280'
                END,
                video_resolution = '720p'
            """
        )
    )


def downgrade() -> None:
    pass
