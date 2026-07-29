from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import CostEntryType


class OperationCostPolicyRead(BaseModel):
    provider: str
    operation: str
    unit: str
    unit_cost: Decimal
    currency: str = "USD"


class CostEstimateRequest(BaseModel):
    generation_count: int = Field(gt=0)
    average_units: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    uncertainty_ratio: Decimal = Field(default=Decimal("0.15"), ge=0)


class CostEstimateRead(BaseModel):
    estimated: Decimal
    minimum: Decimal
    maximum: Decimal


class OperationCostEstimateRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=120)
    quantity: Decimal = Field(gt=0)
    provider: str = Field(default="omniroute", min_length=1, max_length=120)
    model: str | None = Field(default=None, max_length=180)
    uncertainty_ratio: Decimal = Field(default=Decimal("0.15"), ge=0)


class OperationCostEstimateRead(BaseModel):
    provider: str
    model: str | None
    operation: str
    quantity: Decimal
    unit: str
    unit_cost: Decimal
    currency: str
    estimated: Decimal
    minimum: Decimal
    maximum: Decimal


class CostBudgetUpdate(BaseModel):
    project_budget_usd: Decimal | None = Field(default=None, ge=0)
    stage_budgets_usd: dict[str, Decimal] = Field(default_factory=dict)


class CostBudgetRead(BaseModel):
    project_id: UUID
    project_budget_usd: Decimal | None = None
    stage_budgets_usd: dict[str, Decimal] = Field(default_factory=dict)
    currency: str = "USD"


class BudgetCheckRequest(BaseModel):
    project_id: UUID
    estimated_cost: Decimal = Field(ge=0)
    stage: str | None = Field(default=None, max_length=120)


class BudgetCheckRead(BaseModel):
    allowed: bool
    current_cost: Decimal
    estimated_cost: Decimal
    projected_cost: Decimal
    limit: Decimal | None = None
    stage: str | None = None


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
    metadata_json: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CostBreakdownItemRead(BaseModel):
    key: str
    estimated_cost: Decimal = Decimal("0.000000")
    actual_cost: Decimal = Decimal("0.000000")
    credit: Decimal = Decimal("0.000000")
    total_cost: Decimal = Decimal("0.000000")


class ProjectCostSummaryRead(BaseModel):
    project_id: UUID
    currency: str = "USD"
    estimated_cost: Decimal = Decimal("0.000000")
    actual_cost: Decimal = Decimal("0.000000")
    credit: Decimal = Decimal("0.000000")
    total_cost: Decimal = Decimal("0.000000")
    estimated_vs_actual_delta: Decimal = Decimal("0.000000")
    by_stage: list[CostBreakdownItemRead] = Field(default_factory=list)
    by_provider: list[CostBreakdownItemRead] = Field(default_factory=list)
    by_model: list[CostBreakdownItemRead] = Field(default_factory=list)
