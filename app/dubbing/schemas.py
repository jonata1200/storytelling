from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DubbingStartRequest(BaseModel):
    source_language: str | None = None
    target_language: str | None = None


class DubbingJobRead(BaseModel):
    id: UUID
    project_id: UUID
    export_id: UUID
    result_artifact_id: UUID | None
    result_asset_id: UUID | None
    provider: str
    model: str
    external_job_id: str | None
    status: str
    progress: int
    source_language: str | None
    target_language: str
    result_uri: str | None
    cost_estimate: Decimal
    error: str | None
    metadata_json: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
