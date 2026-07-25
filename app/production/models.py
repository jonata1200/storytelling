from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProjectProductionSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_production_settings"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_production_settings_project_id"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    parent_project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    episode_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), default="short_drama", nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(20), default="9:16", nullable=False)
    image_resolution: Mapped[str] = mapped_column(String(40), default="1080x1920", nullable=False)
    video_resolution: Mapped[str] = mapped_column(String(40), default="1080x1920", nullable=False)
    workflow_mode: Mapped[str] = mapped_column(String(80), default="keyframes_i2v", nullable=False)
    image_model: Mapped[str] = mapped_column(
        String(160),
        default="sourceful/riverflow-v2-fast",
        nullable=False,
    )
    video_model: Mapped[str] = mapped_column(
        String(160),
        default="bytedance/seedance-2.0-fast",
        nullable=False,
    )
    audio_mode: Mapped[str] = mapped_column(
        String(80), default="narration_subtitles", nullable=False
    )
    motion_intensity: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
