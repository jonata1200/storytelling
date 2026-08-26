from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class StoryboardFrame(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "storyboard_frames"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    shot_id: Mapped[UUID] = mapped_column(ForeignKey("shots.id"), nullable=False, index=True)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    frame_number: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    narration_text: Mapped[str] = mapped_column(Text, nullable=False)
    dialogue_text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class AudioTrack(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audio_tracks"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(220), nullable=False)
    track_type: Mapped[str] = mapped_column(String(80), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    alignment: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Animatic(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "animatics"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    audio_track_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("audio_tracks.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(220), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Timeline(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "timelines"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    animatic_id: Mapped[UUID | None] = mapped_column(ForeignKey("animatics.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(220), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class TimelineItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "timeline_items"

    timeline_id: Mapped[UUID] = mapped_column(
        ForeignKey("timelines.id"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    source_artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    source_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    layer: Mapped[str] = mapped_column(String(80), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
