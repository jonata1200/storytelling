from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Briefing(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "briefings"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    theme: Mapped[str] = mapped_column(String(220), nullable=False)
    audience: Mapped[str] = mapped_column(String(220), nullable=False)
    genre: Mapped[str] = mapped_column(String(120), nullable=False)
    primary_emotion: Mapped[str] = mapped_column(String(120), nullable=False)
    emotional_intensity: Mapped[int] = mapped_column(Integer, nullable=False)
    ending_type: Mapped[str] = mapped_column(String(120), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    country_context: Mapped[str] = mapped_column(String(120), nullable=False)
    desired_duration_minutes: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    has_narrator: Mapped[bool] = mapped_column(nullable=False)
    visual_style: Mapped[str] = mapped_column(String(220), nullable=False)
    content_objective: Mapped[str] = mapped_column(String(220), nullable=False)
    call_to_action: Mapped[str | None] = mapped_column(String(220), nullable=True)
    constraints: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)


class StoryIdea(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "story_ideas"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    hook: Mapped[str] = mapped_column(Text, nullable=False)
    premise: Mapped[str] = mapped_column(Text, nullable=False)
    protagonist: Mapped[str] = mapped_column(String(220), nullable=False)
    retention_potential: Mapped[int] = mapped_column(Integer, nullable=False)
    cliche_risk: Mapped[int] = mapped_column(Integer, nullable=False)
    production_complexity: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Script(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scripts"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    story_idea_id: Mapped[UUID] = mapped_column(ForeignKey("story_ideas.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    target_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    story_hook: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ScriptVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "script_versions"
    __table_args__ = (
        UniqueConstraint("script_id", "version_number", name="uq_script_version_number"),
    )

    script_id: Mapped[UUID] = mapped_column(ForeignKey("scripts.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Scene(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scenes"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    script_id: Mapped[UUID] = mapped_column(ForeignKey("scripts.id"), nullable=False, index=True)
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Shot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shots"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    scene_id: Mapped[UUID] = mapped_column(ForeignKey("scenes.id"), nullable=False, index=True)
    shot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    narration_text: Mapped[str] = mapped_column(Text, nullable=False)
    dialogue_text: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    emotion: Mapped[str] = mapped_column(String(120), nullable=False)
    visual_composition: Mapped[str] = mapped_column(Text, nullable=False)
    camera_movement: Mapped[str] = mapped_column(String(120), nullable=False)
    generation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
