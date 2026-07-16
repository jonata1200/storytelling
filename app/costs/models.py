from decimal import Decimal
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import CostEntryType
from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CostEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cost_entries"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    entry_type: Mapped[CostEntryType] = mapped_column(
        Enum(CostEntryType, name="cost_entry_type"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str | None] = mapped_column(String(180), nullable=True)
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
