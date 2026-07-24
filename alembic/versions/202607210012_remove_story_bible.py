"""remove story bible stage

Revision ID: 202607210012
Revises: 202607170011
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607210012"
down_revision: str | None = "202607170011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _foreign_key_name(
    table_name: str, column_name: str, referred_table: str
) -> str | None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
            SELECT tc.constraint_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name = :table_name
              AND kcu.column_name = :column_name
              AND ccu.table_name = :referred_table
            LIMIT 1
            """
        ),
        {
            "table_name": table_name,
            "column_name": column_name,
            "referred_table": referred_table,
        },
    )
    return result.scalar_one_or_none()


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _backfill_story_idea_ids() -> None:
    if not _table_exists("story_bibles") or not _table_exists("scripts"):
        return
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT s.id AS script_id, sb.story_idea_id
            FROM scripts AS s
            JOIN story_bibles AS sb ON s.story_bible_id = sb.id
            WHERE s.story_idea_id IS NULL
            """
        )
    ).all()
    for row in rows:
        bind.execute(
            sa.text(
                """
                UPDATE scripts
                SET story_idea_id = :story_idea_id
                WHERE id = :script_id
                """
            ),
            {"script_id": row.script_id, "story_idea_id": row.story_idea_id},
        )
    remaining = bind.execute(
        sa.text("SELECT COUNT(*) FROM scripts WHERE story_idea_id IS NULL")
    ).scalar_one()
    if int(remaining or 0) > 0:
        raise RuntimeError(
            "Nao foi possivel migrar scripts.story_bible_id para story_idea_id sem perda de dados."
        )


def upgrade() -> None:
    with op.batch_alter_table("scripts") as batch_op:
        batch_op.add_column(sa.Column("story_idea_id", sa.Uuid(), nullable=True))

    _backfill_story_idea_ids()

    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        fk_name = _foreign_key_name("scripts", "story_bible_id", "story_bibles")
        if fk_name:
            op.drop_constraint(fk_name, "scripts", type_="foreignkey")
    with op.batch_alter_table("scripts") as batch_op:
        batch_op.drop_column("story_bible_id")
        batch_op.create_foreign_key(
            "scripts_story_idea_id_fkey",
            "story_ideas",
            ["story_idea_id"],
            ["id"],
        )
        batch_op.alter_column("story_idea_id", nullable=False)

    if _table_exists("story_bibles"):
        op.drop_index(op.f("ix_story_bibles_project_id"), table_name="story_bibles")
        op.drop_table("story_bibles")


def downgrade() -> None:
    with op.batch_alter_table("scripts") as batch_op:
        batch_op.add_column(sa.Column("story_bible_id", sa.Uuid(), nullable=True))
        batch_op.drop_constraint("scripts_story_idea_id_fkey", type_="foreignkey")
        batch_op.drop_column("story_idea_id")

    op.create_table(
        "story_bibles",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("story_idea_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("logline", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["story_idea_id"], ["story_ideas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_story_bibles_project_id"), "story_bibles", ["project_id"])
