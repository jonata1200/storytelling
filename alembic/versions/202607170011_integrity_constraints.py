"""integrity constraints

Revision ID: 202607170011
Revises: 202607160010
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607170011"
down_revision: str | None = "202607160010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


VERSION_CONSTRAINTS = (
    ("project_versions", "project_id", "uq_project_version_number"),
    ("artifact_versions", "artifact_id", "uq_artifact_version_number"),
    ("asset_versions", "asset_id", "uq_asset_version_number"),
    ("script_versions", "script_id", "uq_script_version_number"),
    ("character_versions", "character_id", "uq_character_version_number"),
    ("location_versions", "location_id", "uq_location_version_number"),
    ("prop_versions", "prop_id", "uq_prop_version_number"),
)


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id, row_number() OVER (
                    PARTITION BY storyboard_frame_id ORDER BY created_at DESC, id DESC
                ) AS position
                FROM video_clips WHERE selected = true
            )
            UPDATE video_clips SET selected = false
            WHERE id IN (SELECT id FROM ranked WHERE position > 1)
            """
        )
    )
    for table, parent_column, name in VERSION_CONSTRAINTS:
        op.create_unique_constraint(name, table, [parent_column, "version_number"])
    op.create_index(
        "uq_video_clip_selected_per_frame",
        "video_clips",
        ["storyboard_frame_id"],
        unique=True,
        postgresql_where=sa.text("selected"),
    )


def downgrade() -> None:
    op.drop_index("uq_video_clip_selected_per_frame", table_name="video_clips")
    for table, _parent_column, name in reversed(VERSION_CONSTRAINTS):
        op.drop_constraint(name, table, type_="unique")
