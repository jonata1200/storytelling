"""Add safe delete rules to QA result relationships.

Revision ID: 202609010038
Revises: 202608270037
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202609010038"
down_revision: str | None = "202608270037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    relationships = (
        (
            "fk_qa_results_project_id_projects",
            "projects",
            ["project_id"],
            "CASCADE",
        ),
        (
            "fk_qa_results_shot_id_shots",
            "shots",
            ["shot_id"],
            "CASCADE",
        ),
        (
            "fk_qa_results_segment_id_continuous_video_segments",
            "continuous_video_segments",
            ["segment_id"],
            "CASCADE",
        ),
        (
            "fk_qa_results_generation_job_id_generation_jobs",
            "generation_jobs",
            ["generation_job_id"],
            "SET NULL",
        ),
    )
    for constraint_name, target_table, local_columns, ondelete in relationships:
        op.drop_constraint(constraint_name, "qa_results", type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            "qa_results",
            target_table,
            local_columns,
            ["id"],
            ondelete=ondelete,
        )


def downgrade() -> None:
    relationships = (
        ("fk_qa_results_project_id_projects", "projects", ["project_id"]),
        ("fk_qa_results_shot_id_shots", "shots", ["shot_id"]),
        (
            "fk_qa_results_segment_id_continuous_video_segments",
            "continuous_video_segments",
            ["segment_id"],
        ),
        (
            "fk_qa_results_generation_job_id_generation_jobs",
            "generation_jobs",
            ["generation_job_id"],
        ),
    )
    for constraint_name, target_table, local_columns in relationships:
        op.drop_constraint(constraint_name, "qa_results", type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            "qa_results",
            target_table,
            local_columns,
            ["id"],
        )
