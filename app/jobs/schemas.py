from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import GenerationJobStatus, GenerationJobType


class JobCreate(BaseModel):
    step: str = Field(min_length=2, max_length=80)
    payload: dict = Field(default_factory=dict)


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    job_type: GenerationJobType
    status: GenerationJobStatus
    progress: int
    attempts: int
    max_attempts: int
    provider: str
    model: str
    idempotency_key: str
    request_payload: dict
    response_payload: dict
    cost_estimate: Decimal
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
