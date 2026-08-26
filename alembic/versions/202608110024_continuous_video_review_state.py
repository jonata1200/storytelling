"""continuous video review state

Revision ID: 202608110024
Revises: 202608110023
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608110024"
down_revision: str | None = "202608110023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("continuous_video_segments", sa.Column("script_id", sa.Uuid(), nullable=True))
    op.add_column(
        "continuous_video_segments",
        sa.Column(
            "review_status",
            sa.String(length=40),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "continuous_video_segments",
        sa.Column("generated_video_asset_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "continuous_video_segments",
        sa.Column("source_frame_asset_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "continuous_video_segments",
        sa.Column("final_frame_asset_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_continuous_video_segments_script_id_scripts",
        "continuous_video_segments",
        "scripts",
        ["script_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_continuous_video_segments_generated_video_asset_id_assets",
        "continuous_video_segments",
        "assets",
        ["generated_video_asset_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_continuous_video_segments_source_frame_asset_id_assets",
        "continuous_video_segments",
        "assets",
        ["source_frame_asset_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_continuous_video_segments_final_frame_asset_id_assets",
        "continuous_video_segments",
        "assets",
        ["final_frame_asset_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_continuous_video_segments_review_status"),
        "continuous_video_segments",
        ["review_status"],
        unique=False,
    )
    op.create_index(
        "ix_continuous_video_segments_project_script_segment",
        "continuous_video_segments",
        ["project_id", "script_id", "segment_number"],
        unique=False,
    )
    op.create_index(
        "ix_continuous_video_segments_project_review_status",
        "continuous_video_segments",
        ["project_id", "review_status", "segment_number"],
        unique=False,
    )
    op.execute(
        """
        UPDATE continuous_video_segments
        SET review_status = CASE
            WHEN status = 'SUCCEEDED' THEN 'ready_for_review'
            WHEN status = 'RUNNING' THEN 'generating'
            WHEN status = 'FAILED' THEN 'failed'
            ELSE 'pending'
        END,
        generated_video_asset_id = asset_id
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_continuous_video_segments_project_review_status",
        table_name="continuous_video_segments",
    )
    op.drop_index(
        "ix_continuous_video_segments_project_script_segment",
        table_name="continuous_video_segments",
    )
    op.drop_index(
        op.f("ix_continuous_video_segments_review_status"),
        table_name="continuous_video_segments",
    )
    op.drop_constraint(
        "fk_continuous_video_segments_final_frame_asset_id_assets",
        "continuous_video_segments",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_continuous_video_segments_source_frame_asset_id_assets",
        "continuous_video_segments",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_continuous_video_segments_generated_video_asset_id_assets",
        "continuous_video_segments",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_continuous_video_segments_script_id_scripts",
        "continuous_video_segments",
        type_="foreignkey",
    )
    op.drop_column("continuous_video_segments", "final_frame_asset_id")
    op.drop_column("continuous_video_segments", "source_frame_asset_id")
    op.drop_column("continuous_video_segments", "generated_video_asset_id")
    op.drop_column("continuous_video_segments", "review_status")
    op.drop_column("continuous_video_segments", "script_id")
