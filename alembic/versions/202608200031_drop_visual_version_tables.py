"""drop character_versions and location_versions

A etapa de geração da Biblioteca Visual foi removida da aplicação.
As tabelas ``character_versions`` e ``location_versions`` eram usadas
apenas internamente pelo módulo de visual bible para rastrear versões
de personagens e locais — nenhum outro módulo depende delas.

Esta migration remove as duas tabelas e seus dados.

Downgrade é intencionalmente um no-op: recriar as tabelas não restauraria
o comportamento removido.

Revision ID: 202608200031
Revises: 202608170030
Create Date: 2026-08-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608200031"
down_revision: str | None = "202608170030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop location_versions first (no other table depends on it)
    op.drop_index(
        op.f("ix_location_versions_location_id"),
        table_name="location_versions",
    )
    op.drop_table("location_versions")

    # Drop character_versions (no other table depends on it)
    op.drop_index(
        op.f("ix_character_versions_character_id"),
        table_name="character_versions",
    )
    op.drop_table("character_versions")


def downgrade() -> None:
    """Destructive migration: dropping the removed tables is not reversible.

    Restore from a backup taken before ``upgrade()``.
    """
    pass
