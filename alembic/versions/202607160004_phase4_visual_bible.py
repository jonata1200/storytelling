"""phase 4 visual bible

Revision ID: 202607160004
Revises: 202607160003
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607160004"
down_revision: str | None = "202607160003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE artifact_type ADD VALUE IF NOT EXISTS 'VISUAL_REFERENCE'")

    op.create_table(
        "characters",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("role", sa.String(length=120), nullable=False),
        sa.Column("canonical_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("character_fingerprint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_characters_project_id"), "characters", ["project_id"])

    op.create_table(
        "character_versions",
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("canonical_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_character_versions_character_id"),
        "character_versions",
        ["character_id"],
    )

    op.create_table(
        "locations",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("canonical_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_locations_project_id"), "locations", ["project_id"])

    op.create_table(
        "location_versions",
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("canonical_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_location_versions_location_id"),
        "location_versions",
        ["location_id"],
    )

    op.create_table(
        "props",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("narrative_importance", sa.String(length=220), nullable=False),
        sa.Column("canonical_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_props_project_id"), "props", ["project_id"])

    op.create_table(
        "prop_versions",
        sa.Column("prop_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("canonical_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["prop_id"], ["props.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_prop_versions_prop_id"), "prop_versions", ["prop_id"])

    op.create_table(
        "visual_references",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("target_kind", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("view_type", sa.String(length=80), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_visual_references_project_id"), "visual_references", ["project_id"]
    )
    op.create_index(op.f("ix_visual_references_target_id"), "visual_references", ["target_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_visual_references_target_id"), table_name="visual_references")
    op.drop_index(op.f("ix_visual_references_project_id"), table_name="visual_references")
    op.drop_table("visual_references")
    op.drop_index(op.f("ix_prop_versions_prop_id"), table_name="prop_versions")
    op.drop_table("prop_versions")
    op.drop_index(op.f("ix_props_project_id"), table_name="props")
    op.drop_table("props")
    op.drop_index(op.f("ix_location_versions_location_id"), table_name="location_versions")
    op.drop_table("location_versions")
    op.drop_index(op.f("ix_locations_project_id"), table_name="locations")
    op.drop_table("locations")
    op.drop_index(op.f("ix_character_versions_character_id"), table_name="character_versions")
    op.drop_table("character_versions")
    op.drop_index(op.f("ix_characters_project_id"), table_name="characters")
    op.drop_table("characters")
