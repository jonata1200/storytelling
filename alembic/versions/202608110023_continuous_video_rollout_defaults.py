"""continuous video rollout defaults

Revision ID: 202608110023
Revises: 202608110022
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608110023"
down_revision: str | None = "202608110022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE project_production_settings
        SET workflow_mode = 'keyframes_i2v'
        WHERE workflow_mode IS NULL OR btrim(workflow_mode) = ''
        """
    )
    op.execute(
        """
        UPDATE project_production_settings
        SET video_model = 'veo-3.1-generate-preview'
        WHERE video_model IS NULL
           OR btrim(video_model) = ''
           OR video_model = 'veo-3.1-lite-generate-preview'
        """
    )
    op.execute(
        """
        UPDATE continuous_video_plans
        SET mode = 'continuous_fast'
        WHERE mode IS NULL OR btrim(mode) = ''
        """
    )
    op.execute(
        """
        UPDATE continuous_video_segments
        SET provider = 'google_ai'
        WHERE provider IS NULL OR btrim(provider) = ''
        """
    )
    op.execute(
        """
        UPDATE continuous_video_segments
        SET model = 'veo-3.1-fast-generate-preview'
        WHERE model IS NULL OR btrim(model) = ''
        """
    )
    op.alter_column(
        "project_production_settings",
        "workflow_mode",
        existing_type=sa.String(length=80),
        nullable=False,
        server_default="keyframes_i2v",
    )
    op.alter_column(
        "project_production_settings",
        "video_model",
        existing_type=sa.String(length=160),
        nullable=False,
        server_default="veo-3.1-generate-preview",
    )
    op.alter_column(
        "continuous_video_plans",
        "mode",
        existing_type=sa.String(length=80),
        nullable=False,
        server_default="continuous_fast",
    )
    op.alter_column(
        "continuous_video_segments",
        "provider",
        existing_type=sa.String(length=120),
        nullable=False,
        server_default="google_ai",
    )
    op.alter_column(
        "continuous_video_segments",
        "model",
        existing_type=sa.String(length=160),
        nullable=False,
        server_default="veo-3.1-fast-generate-preview",
    )


def downgrade() -> None:
    op.alter_column(
        "continuous_video_segments",
        "model",
        existing_type=sa.String(length=160),
        server_default=None,
    )
    op.alter_column(
        "continuous_video_segments",
        "provider",
        existing_type=sa.String(length=120),
        server_default=None,
    )
    op.alter_column(
        "continuous_video_plans",
        "mode",
        existing_type=sa.String(length=80),
        server_default=None,
    )
    op.alter_column(
        "project_production_settings",
        "video_model",
        existing_type=sa.String(length=160),
        server_default=None,
    )
    op.alter_column(
        "project_production_settings",
        "workflow_mode",
        existing_type=sa.String(length=80),
        server_default=None,
    )
