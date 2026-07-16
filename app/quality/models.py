from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ContinuityState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "continuity_states"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    shot_id: Mapped[UUID | None] = mapped_column(ForeignKey("shots.id"), nullable=True, index=True)
    storyboard_frame_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("storyboard_frames.id"), nullable=True
    )
    timeline_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("timeline_items.id"), nullable=True
    )
    source_artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    previous_state_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("continuity_states.id"), nullable=True
    )
    scene_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shot_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    accepted: Mapped[bool] = mapped_column(default=False, nullable=False)


class ContinuityIssue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "continuity_issues"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    continuity_state_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("continuity_states.id"), nullable=True, index=True
    )
    source_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id"), nullable=True
    )
    issue_code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    actual: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    accepted: Mapped[bool] = mapped_column(default=False, nullable=False)
    accepted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class QualityCheck(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quality_checks"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    target_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id"), nullable=True
    )
    check_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
