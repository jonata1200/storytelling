"""Add QA results and media job enum values.

Revision ID: 202608260035
Revises: 202608260034
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202608260035"
down_revision: str | None = "202608260034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE generation_job_type ADD VALUE IF NOT EXISTS 'INGREDIENT'")
    op.execute("ALTER TYPE generation_job_type ADD VALUE IF NOT EXISTS 'QA'")
    op.create_table(
        "qa_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("shot_id", sa.Uuid(), nullable=False),
        sa.Column("segment_id", sa.Uuid(), nullable=False),
        sa.Column("generation_job_id", sa.Uuid(), nullable=True),
        sa.Column("total_score", sa.Integer(), nullable=False),
        sa.Column("dimension_scores", postgresql.JSONB(), nullable=False),
        sa.Column("reasons", postgresql.JSONB(), nullable=False),
        sa.Column("objective_failures", postgresql.JSONB(), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False),
        sa.Column("compiler_version", sa.String(length=80), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["generation_job_id"], ["generation_jobs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["segment_id"], ["continuous_video_segments.id"]),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("project_id", "shot_id", "segment_id", "generation_job_id", "decision"):
        op.create_index(f"ix_qa_results_{column}", "qa_results", [column], unique=False)


def downgrade() -> None:
    op.drop_table("qa_results")
    # PostgreSQL enum values are intentionally retained: removing them safely requires
    # rebuilding the enum and may invalidate historical GenerationJob rows.
