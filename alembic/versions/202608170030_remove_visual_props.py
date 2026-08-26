"""remove props from the visual bible

Objetos (props) foram removidos da Biblioteca Visual: agora ela cria apenas
personagens e locais. Esta migration apaga o que ficou para trás do recurso:

- linhas de ``props`` e ``prop_versions`` (tabelas são dropadas);
- artefatos ``PROP`` e suas versões/aprovações/dependências/custos/execuções;
- ``visual_references`` com ``target_kind = 'prop'`` e seus assets;
- o valor ``PROP`` do enum ``artifact_type``.

Esta migration é destrutiva: as tabelas/colunas abaixo são dropadas junto com
seus dados. Faça um backup antes de rodá-la em qualquer ambiente que não seja
uma cópia de desenvolvimento descartável.

O downgrade() é intencionalmente um no-op: recriar as tabelas dropadas não
restauraria o comportamento do recurso removido.

Revision ID: 202608170030
Revises: 202608170029
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608170030"
down_revision: str | None = "202608170029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pre-flight check: ensure a backup was taken before running this destructive migration.
    import os

    if os.environ.get("SKIP_BACKUP_CHECK") != "1":
        import sys

        print(
            "WARNING: This migration is destructive and irreversible. "
            "Ensure a full database backup was taken before proceeding. "
            "Set SKIP_BACKUP_CHECK=1 to suppress this warning.",
            file=sys.stderr,
        )

    # Capture the artifacts (PROP + VISUAL_REFERENCE of prop targets) and assets
    # that must be removed before deleting rows, since the subqueries depend on
    # rows that are deleted in the process.
    op.execute(
        """
        CREATE TEMP TABLE tmp_prop_artifact_ids AS
        SELECT id AS artifact_id FROM artifacts WHERE artifact_type = 'PROP'
        UNION
        SELECT artifact_id FROM visual_references WHERE target_kind = 'prop'
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE tmp_prop_asset_ids AS
        SELECT asset_id FROM visual_references
        WHERE target_kind = 'prop' AND asset_id IS NOT NULL
        """
    )

    # ------------------------------------------------------------------
    # Clean everything pointing at the removed prop artifacts.
    # ------------------------------------------------------------------
    op.execute(
        """
        DELETE FROM approvals
        WHERE artifact_id IN (SELECT artifact_id FROM tmp_prop_artifact_ids)
           OR artifact_version_id IN (
                SELECT artifact_versions.id
                FROM artifact_versions
                JOIN tmp_prop_artifact_ids
                    ON tmp_prop_artifact_ids.artifact_id = artifact_versions.artifact_id
           )
        """
    )
    op.execute(
        """
        DELETE FROM artifact_dependencies
        WHERE upstream_artifact_id IN (SELECT artifact_id FROM tmp_prop_artifact_ids)
           OR downstream_artifact_id IN (SELECT artifact_id FROM tmp_prop_artifact_ids)
        """
    )
    op.execute(
        """
        DELETE FROM operational_events
        WHERE artifact_id IN (SELECT artifact_id FROM tmp_prop_artifact_ids)
        """
    )
    op.execute(
        """
        DELETE FROM cost_entries
        WHERE artifact_id IN (SELECT artifact_id FROM tmp_prop_artifact_ids)
        """
    )
    op.execute(
        """
        DELETE FROM prompt_executions
        WHERE artifact_id IN (SELECT artifact_id FROM tmp_prop_artifact_ids)
        """
    )
    op.execute(
        """
        DELETE FROM artifact_versions
        WHERE artifact_id IN (SELECT artifact_id FROM tmp_prop_artifact_ids)
        """
    )

    # ------------------------------------------------------------------
    # Props and prop_versions: delete rows BEFORE artifacts, since they
    # have FK references to artifacts.id.
    # ------------------------------------------------------------------
    op.execute("DELETE FROM prop_versions")
    op.execute("DELETE FROM props")

    # ------------------------------------------------------------------
    # Prop visual references: remove ALL visual_references that point to
    # prop assets (regardless of target_kind) before deleting the assets
    # themselves, to avoid FK violations.
    # ------------------------------------------------------------------
    op.execute(
        """
        DELETE FROM visual_references
        WHERE asset_id IN (SELECT asset_id FROM tmp_prop_asset_ids)
        """
    )
    op.execute(
        """
        DELETE FROM asset_versions
        WHERE asset_id IN (SELECT asset_id FROM tmp_prop_asset_ids)
        """
    )
    op.execute(
        """
        DELETE FROM assets
        WHERE id IN (SELECT asset_id FROM tmp_prop_asset_ids)
        """
    )
    op.execute(
        """
        DELETE FROM artifacts
        WHERE id IN (SELECT artifact_id FROM tmp_prop_artifact_ids)
        """
    )

    # ------------------------------------------------------------------
    # Drop the props tables (already emptied above).
    # ------------------------------------------------------------------
    op.drop_index(op.f("ix_prop_versions_prop_id"), table_name="prop_versions")
    op.drop_table("prop_versions")
    op.drop_index(op.f("ix_props_project_id"), table_name="props")
    op.drop_table("props")

    # ------------------------------------------------------------------
    # Enum cleanup: recreate artifact_type without the 'PROP' label.
    # ------------------------------------------------------------------
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
            'SCENE',
            'SHOT',
            'STORYBOARD',
            'VISUAL_REFERENCE',
            'ANIMATIC',
            'VIDEO_CLIP',
            'AUDIO_TRACK',
            'TIMELINE'
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

    Restore from a backup taken before `upgrade()`.
    """
    pass
