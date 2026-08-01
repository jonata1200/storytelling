from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DubbingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dubbing_jobs"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    export_id: Mapped[UUID] = mapped_column(ForeignKey("exports.id"), nullable=False, index=True)
    result_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id"), nullable=True
    )
    result_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    external_job_id: Mapped[str | None] = mapped_column(String(220), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="PENDING")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    target_language: Mapped[str] = mapped_column(String(16), nullable=False)
    result_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    cost_estimate: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
