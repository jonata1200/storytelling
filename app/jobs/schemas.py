import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import GenerationJobStatus, GenerationJobType

JOB_PAYLOAD_MAX_BYTES = 256 * 1024


class JobCreate(BaseModel):
    step: str = Field(min_length=2, max_length=80)
    payload: dict = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _validate_payload_size(cls, value: dict) -> dict:
        serialized = json.dumps(value, default=str, ensure_ascii=True)
        if len(serialized.encode("utf-8")) > JOB_PAYLOAD_MAX_BYTES:
            raise ValueError(
                f"payload excede o limite de {JOB_PAYLOAD_MAX_BYTES} bytes "
                f"({len(serialized.encode('utf-8'))} bytes)"
            )
        return value


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
