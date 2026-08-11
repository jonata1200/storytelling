from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
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


class ContinuousVideoPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "continuous_video_plans"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_continuous_video_plans_project_id"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(
        String(80),
        default="continuous_fast",
        server_default="continuous_fast",
        nullable=False,
    )
    target_duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    segment_duration_seconds: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    segment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ContinuousVideoSegment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "continuous_video_segments"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "segment_number",
            name="uq_continuous_video_segments_project_segment",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_continuous_video_segments_idempotency_key",
        ),
        Index(
            "ix_continuous_video_segments_project_status",
            "project_id",
            "status",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    segment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(220), default="", nullable=False)
    prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    status: Mapped[GenerationJobStatus] = mapped_column(
        Enum(GenerationJobStatus, name="generation_job_status"),
        default=GenerationJobStatus.PENDING,
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(120),
        default="google_ai",
        server_default="google_ai",
        nullable=False,
    )
    model: Mapped[str] = mapped_column(
        String(160),
        default="veo-3.1-fast-generate-preview",
        server_default="veo-3.1-fast-generate-preview",
        nullable=False,
    )
    generation_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("generation_jobs.id"),
        nullable=True,
        index=True,
    )
    asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    source_segment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("continuous_video_segments.id"),
        nullable=True,
    )
    source_video_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assets.id"),
        nullable=True,
    )
    external_operation_id: Mapped[str | None] = mapped_column(
        String(220),
        nullable=True,
        index=True,
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    cost_estimate: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
