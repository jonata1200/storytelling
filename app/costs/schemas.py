from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import CostEntryType


class CostEstimateRequest(BaseModel):
    generation_count: int = Field(gt=0)
    average_units: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    uncertainty_ratio: Decimal = Field(default=Decimal("0.15"), ge=0)


class CostEstimateRead(BaseModel):
    estimated: Decimal
    minimum: Decimal
    maximum: Decimal


class CostEntryCreate(BaseModel):
    project_id: UUID
    artifact_id: UUID | None = None
    entry_type: CostEntryType
    provider: str = Field(min_length=1, max_length=120)
    model: str | None = Field(default=None, max_length=180)
    operation: str = Field(min_length=1, max_length=120)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=40)
    unit_cost: Decimal = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    metadata_json: dict = Field(default_factory=dict)


class CostEntryRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID | None
    entry_type: CostEntryType
    provider: str
    model: str | None
    operation: str
    quantity: Decimal
    unit: str
    unit_cost: Decimal
    total_cost: Decimal
    currency: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
