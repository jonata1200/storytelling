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


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute("TRUNCATE TABLE projects RESTART IDENTITY CASCADE")
    else:
        op.execute("DELETE FROM projects")

    with op.batch_alter_table("scripts") as batch_op:
        batch_op.add_column(sa.Column("story_idea_id", sa.Uuid(), nullable=True))

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
