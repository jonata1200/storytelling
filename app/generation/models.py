from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PromptTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompt_templates"

    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    task: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PromptExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompt_executions"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    prompt_template_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_templates.id"), nullable=True
    )
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ProjectModelSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_model_settings"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "task", name="uq_project_model_settings_project_task"
        ),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    task: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(220), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
