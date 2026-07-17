from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ClipReviewDecision, GenerationJobStatus, GenerationJobType
from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GenerationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "generation_jobs"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    source_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id"), nullable=True
    )
    result_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id"), nullable=True
    )
    external_job_id: Mapped[str | None] = mapped_column(String(220), nullable=True, index=True)
    job_type: Mapped[GenerationJobType] = mapped_column(
        Enum(GenerationJobType, name="generation_job_type"), nullable=False
    )
    status: Mapped[GenerationJobStatus] = mapped_column(
        Enum(GenerationJobStatus, name="generation_job_status"),
        default=GenerationJobStatus.PENDING,
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    request_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    response_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    cost_estimate: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VideoClip(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "video_clips"
    __table_args__ = (
        Index(
            "uq_video_clip_selected_per_frame",
            "storyboard_frame_id",
            unique=True,
            postgresql_where=text("selected"),
        ),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    storyboard_frame_id: Mapped[UUID] = mapped_column(
        ForeignKey("storyboard_frames.id"), nullable=False, index=True
    )
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    generation_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("generation_jobs.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    variant_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    selected: Mapped[bool] = mapped_column(default=False, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ClipReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "clip_reviews"

    video_clip_id: Mapped[UUID] = mapped_column(ForeignKey("video_clips.id"), nullable=False)
    reviewer_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision: Mapped[ClipReviewDecision] = mapped_column(
        Enum(ClipReviewDecision, name="clip_review_decision"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
