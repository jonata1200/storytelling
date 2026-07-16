"""phase 2 domain foundation

Revision ID: 202607160002
Revises: 202607160001
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607160002"
down_revision: str | None = "202607160001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dependency_kind = postgresql.ENUM(
        "DERIVED_FROM",
        "REQUIRES_APPROVAL_OF",
        "REFERENCES",
        "INVALIDATES",
        name="dependency_kind",
        create_type=False,
    )
    asset_kind = postgresql.ENUM(
        "IMAGE",
        "VIDEO",
        "AUDIO",
        "SUBTITLE",
        "DOCUMENT",
        "OTHER",
        name="asset_kind",
        create_type=False,
    )
    cost_entry_type = postgresql.ENUM(
        "ESTIMATE",
        "ACTUAL",
        "CREDIT",
        name="cost_entry_type",
        create_type=False,
    )

    dependency_kind.create(op.get_bind(), checkfirst=True)
    asset_kind.create(op.get_bind(), checkfirst=True)
    cost_entry_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "artifact_dependencies",
        sa.Column("upstream_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("downstream_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("dependency_kind", dependency_kind, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["downstream_artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["upstream_artifact_id"], ["artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "upstream_artifact_id",
            "downstream_artifact_id",
            "dependency_kind",
            name="uq_artifact_dependency_edge",
        ),
    )
    op.create_index(
        op.f("ix_artifact_dependencies_downstream_artifact_id"),
        "artifact_dependencies",
        ["downstream_artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_artifact_dependencies_upstream_artifact_id"),
        "artifact_dependencies",
        ["upstream_artifact_id"],
        unique=False,
    )

    op.create_table(
        "assets",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
        sa.Column("kind", asset_kind, nullable=False),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("storage_uri", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_assets_project_id"), "assets", ["project_id"], unique=False)

    op.create_table(
        "asset_versions",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("storage_uri", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_asset_versions_asset_id"), "asset_versions", ["asset_id"], unique=False
    )

    op.create_table(
        "cost_entries",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
        sa.Column("entry_type", cost_entry_type, nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=180), nullable=True),
        sa.Column("operation", sa.String(length=120), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 4), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("total_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cost_entries_project_id"), "cost_entries", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_cost_entries_project_id"), table_name="cost_entries")
    op.drop_table("cost_entries")
    op.drop_index(op.f("ix_asset_versions_asset_id"), table_name="asset_versions")
    op.drop_table("asset_versions")
    op.drop_index(op.f("ix_assets_project_id"), table_name="assets")
    op.drop_table("assets")
    op.drop_index(
        op.f("ix_artifact_dependencies_upstream_artifact_id"),
        table_name="artifact_dependencies",
    )
    op.drop_index(
        op.f("ix_artifact_dependencies_downstream_artifact_id"),
        table_name="artifact_dependencies",
    )
    op.drop_table("artifact_dependencies")
    postgresql.ENUM(name="cost_entry_type").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="asset_kind").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="dependency_kind").drop(op.get_bind(), checkfirst=True)
