"""Link continuous video segments to shots without rewriting ambiguous history.

Revision ID: 202608260034
Revises: 202608260033
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608260034"
down_revision: str | None = "202608260033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("continuous_video_segments", sa.Column("shot_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_continuous_video_segments_shot_id",
        "continuous_video_segments",
        "shots",
        ["shot_id"],
        ["id"],
    )
    op.create_index(
        "ix_continuous_video_segments_shot_id",
        "continuous_video_segments",
        ["shot_id"],
        unique=False,
    )
    # Backfill somente quando metadata identifica exatamente uma cena e um shot
    # e há exatamente um candidato no mesmo projeto/script.
    op.execute(
        """
        UPDATE continuous_video_segments AS segment
        SET shot_id = candidate.id
        FROM shots AS candidate
        JOIN scenes AS scene ON scene.id = candidate.scene_id
        WHERE segment.shot_id IS NULL
          AND segment.script_id = scene.script_id
          AND segment.project_id = candidate.project_id
          AND jsonb_typeof(segment.metadata_json->'source_scene_numbers') = 'array'
          AND jsonb_typeof(segment.metadata_json->'source_shot_numbers') = 'array'
          AND jsonb_array_length(COALESCE(segment.metadata_json->'source_scene_numbers', '[]')) = 1
          AND jsonb_array_length(COALESCE(segment.metadata_json->'source_shot_numbers', '[]')) = 1
          AND scene.scene_number = (segment.metadata_json->'source_scene_numbers'->>0)::integer
          AND candidate.shot_number = (segment.metadata_json->'source_shot_numbers'->>0)::integer
          AND (
              SELECT count(*)
              FROM shots AS check_shot
              JOIN scenes AS check_scene ON check_scene.id = check_shot.scene_id
              WHERE check_shot.project_id = segment.project_id
                AND check_scene.script_id = segment.script_id
                AND check_scene.scene_number =
                    (segment.metadata_json->'source_scene_numbers'->>0)::integer
                AND check_shot.shot_number =
                    (segment.metadata_json->'source_shot_numbers'->>0)::integer
          ) = 1
        """
    )


def downgrade() -> None:
    op.drop_index("ix_continuous_video_segments_shot_id", table_name="continuous_video_segments")
    op.drop_constraint(
        "fk_continuous_video_segments_shot_id",
        "continuous_video_segments",
        type_="foreignkey",
    )
    op.drop_column("continuous_video_segments", "shot_id")
