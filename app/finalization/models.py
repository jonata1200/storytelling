from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SubtitleTrack(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subtitle_tracks"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    audio_track_id: Mapped[UUID] = mapped_column(ForeignKey("audio_tracks.id"), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    safe_area: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Export(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exports"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    timeline_id: Mapped[UUID] = mapped_column(ForeignKey("timelines.id"), nullable=False)
    subtitle_track_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("subtitle_tracks.id"), nullable=True
    )
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False)
    profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    output_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    render_log: Mapped[str | None] = mapped_column(Text, nullable=True)
