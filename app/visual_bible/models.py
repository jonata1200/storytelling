from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Character(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "characters"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(220), nullable=False)
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    canonical_profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    character_fingerprint: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class CharacterVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "character_versions"
    __table_args__ = (
        UniqueConstraint("character_id", "version_number", name="uq_character_version_number"),
    )

    character_id: Mapped[UUID] = mapped_column(
        ForeignKey("characters.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Location(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "locations"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class LocationVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "location_versions"
    __table_args__ = (
        UniqueConstraint("location_id", "version_number", name="uq_location_version_number"),
    )

    location_id: Mapped[UUID] = mapped_column(
        ForeignKey("locations.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class VisualReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "visual_references"
    __table_args__ = (
        Index(
            "uq_visual_reference_canonical_target",
            "target_kind",
            "target_id",
            unique=True,
            postgresql_where=text("is_canonical"),
        ),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    view_type: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="generated", server_default="generated", nullable=False, index=True
    )
    is_canonical: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
