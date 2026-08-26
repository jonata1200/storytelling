"""remove orphan tables and enum values from removed features

Remove what was left behind by the removal of auth (users, user_sessions and
user FK columns), dubbing (dubbing_jobs), finalization (exports, subtitle_tracks)
and quality (quality_checks, continuity_states, continuity_issues), plus the
orphaned enum values (project_status, generation_job_type, artifact_type).

This migration is destructive: the tables/columns below are dropped together
with their data. A backup should be taken before running it anywhere other
than a disposable development copy (see docs/06-fase-6-migracoes-banco.md).

The downgrade() is intentionally a no-op: recreating the dropped tables in a
minimal form would not restore the removed features' behavior, so a coordinated
rollback is not supported for this migration.

Revision ID: 202608130026
Revises: 202608110025
Create Date: 2026-08-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608130026"
down_revision: str | None = "202608110025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pre-flight check: ensure a backup was taken before running this destructive migration.
    # Set env var SKIP_BACKUP_CHECK=1 to bypass (e.g. in CI with ephemeral DBs).
    import os

    if os.environ.get("SKIP_BACKUP_CHECK") != "1":
        import sys

        # Warn loudly — operators should take a backup before this runs.
        # In production, use a backup marker file or env var to confirm.
        print(
            "WARNING: This migration is destructive and irreversible. "
            "Ensure a full database backup was taken before proceeding. "
            "Set SKIP_BACKUP_CHECK=1 to suppress this warning.",
            file=sys.stderr,
        )

    # ------------------------------------------------------------------
    # Dubbing (Fase 3): dubbing_jobs references exports, drop it first.
    # ------------------------------------------------------------------
    op.drop_index(op.f("ix_dubbing_jobs_external_job_id"), table_name="dubbing_jobs")
    op.drop_index(op.f("ix_dubbing_jobs_export_id"), table_name="dubbing_jobs")
    op.drop_index(op.f("ix_dubbing_jobs_project_id"), table_name="dubbing_jobs")
    op.drop_table("dubbing_jobs")

    # ------------------------------------------------------------------
    # Finalization (Fase 4): exports before subtitle_tracks (FK export ->
    # subtitle_tracks). Both also reference artifacts/assets/timelines,
    # which remain.
    # ------------------------------------------------------------------
    op.drop_index(op.f("ix_exports_project_id"), table_name="exports")
    op.drop_table("exports")

    op.drop_index(op.f("ix_subtitle_tracks_project_id"), table_name="subtitle_tracks")
    op.drop_table("subtitle_tracks")

    # ------------------------------------------------------------------
    # Quality (Fase 5): continuity_issues references continuity_states.
    # ------------------------------------------------------------------
    op.drop_index(op.f("ix_quality_checks_project_id"), table_name="quality_checks")
    op.drop_table("quality_checks")

    op.drop_index(
        op.f("ix_continuity_issues_continuity_state_id"),
        table_name="continuity_issues",
    )
    op.drop_index(op.f("ix_continuity_issues_project_id"), table_name="continuity_issues")
    op.drop_table("continuity_issues")

    op.drop_index(op.f("ix_continuity_states_shot_id"), table_name="continuity_states")
    op.drop_index(op.f("ix_continuity_states_project_id"), table_name="continuity_states")
    op.drop_table("continuity_states")

    # ------------------------------------------------------------------
    # Auth (Fase 2): user_sessions references users; drop the user FK
    # columns first (PostgreSQL drops the FK constraint along with the
    # column), then users itself.
    # ------------------------------------------------------------------
    op.drop_index(op.f("ix_user_sessions_email"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_token_hash"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_user_id"), table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_column("approvals", "reviewer_user_id")
    op.drop_column("clip_reviews", "reviewer_user_id")
    op.drop_column("workspaces", "owner_user_id")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    # ------------------------------------------------------------------
    # Enum cleanup. PostgreSQL has no ALTER TYPE ... DROP VALUE, so each
    # enum is recreated without the orphaned labels (rename -> create ->
    # recast column -> drop legacy type). Values still in use by any row
    # are cleared first.
    # ------------------------------------------------------------------
    # project_status: move projects stuck in removed intermediate states
    # straight to COMPLETED (pipeline now ends when clips are generated).
    op.execute(
        """
        UPDATE projects
        SET status = 'COMPLETED'
        WHERE status IN (
            'VIDEO_REVIEW',
            'AUDIO_GENERATION',
            'ASSEMBLY',
            'QUALITY_CONTROL',
            'FINAL_APPROVAL'
        )
        """
    )
    op.execute("ALTER TYPE project_status RENAME TO project_status_legacy")
    op.execute(
        """
        CREATE TYPE project_status AS ENUM (
            'DRAFT',
            'IDEA_GENERATION',
            'IDEA_APPROVAL',
            'STORY_DESIGN',
            'STORY_APPROVAL',
            'SCRIPT_GENERATION',
            'SCRIPT_APPROVAL',
            'VISUAL_BIBLE_GENERATION',
            'VISUAL_BIBLE_APPROVAL',
            'STORYBOARD_GENERATION',
            'STORYBOARD_APPROVAL',
            'PRODUCTION_PLANNING',
            'VIDEO_GENERATION',
            'COMPLETED',
            'FAILED',
            'ARCHIVED'
        )
        """
    )
    op.execute(
        "ALTER TABLE projects ALTER COLUMN status "
        "TYPE project_status USING status::text::project_status"
    )
    op.execute("DROP TYPE project_status_legacy")

    # generation_job_type: 'RENDER' was only used by the finalization step.
    op.execute("DELETE FROM generation_jobs WHERE job_type = 'RENDER'")
    op.execute("ALTER TYPE generation_job_type RENAME TO generation_job_type_legacy")
    op.execute(
        """
        CREATE TYPE generation_job_type AS ENUM (
            'IMAGE',
            'VIDEO',
            'SPEECH',
            'ANALYSIS'
        )
        """
    )
    op.execute(
        "ALTER TABLE generation_jobs ALTER COLUMN job_type "
        "TYPE generation_job_type USING job_type::text::generation_job_type"
    )
    op.execute("DROP TYPE generation_job_type_legacy")

    # artifact_type: 'EXPORT' was only used by the finalization step; clean
    # up the orphaned export artifacts (and everything pointing at them).
    op.execute(
        """
        DELETE FROM artifact_dependencies
        WHERE upstream_artifact_id IN (
            SELECT id FROM artifacts WHERE artifact_type = 'EXPORT'
        )
           OR downstream_artifact_id IN (
            SELECT id FROM artifacts WHERE artifact_type = 'EXPORT'
        )
        """
    )
    op.execute(
        """
        DELETE FROM approvals
        WHERE artifact_id IN (SELECT id FROM artifacts WHERE artifact_type = 'EXPORT')
           OR artifact_version_id IN (
                SELECT id FROM artifact_versions
                WHERE artifact_id IN (
                    SELECT id FROM artifacts WHERE artifact_type = 'EXPORT'
                )
           )
        """
    )
    op.execute(
        """
        DELETE FROM artifact_versions
        WHERE artifact_id IN (SELECT id FROM artifacts WHERE artifact_type = 'EXPORT')
        """
    )
    op.execute("DELETE FROM artifacts WHERE artifact_type = 'EXPORT'")
    op.execute("ALTER TYPE artifact_type RENAME TO artifact_type_legacy")
    op.execute(
        """
        CREATE TYPE artifact_type AS ENUM (
            'BRIEFING',
            'STORY_IDEA',
            'STORY_BIBLE',
            'SCRIPT',
            'CHARACTER',
            'LOCATION',
            'PROP',
            'SCENE',
            'SHOT',
            'STORYBOARD',
            'ANIMATIC',
            'VIDEO_CLIP',
            'AUDIO_TRACK',
            'TIMELINE',
            'VISUAL_REFERENCE'
        )
        """
    )
    op.execute(
        "ALTER TABLE artifacts ALTER COLUMN artifact_type "
        "TYPE artifact_type USING artifact_type::text::artifact_type"
    )
    op.execute("DROP TYPE artifact_type_legacy")


def downgrade() -> None:
    """Destructive migration: dropping the removed tables is not reversible.

    Recreating the dropped tables in a minimal form would not restore the
    removed features (auth, dubbing, finalization, quality), so a downgrade is
    intentionally a no-op. Restore from a backup taken before `upgrade()`.
    """
    pass
