from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GenerateVisualBibleRequest(BaseModel):
    script_id: UUID


class GenerateVisualReferencesRequest(BaseModel):
    target_kind: Literal["character", "location"]
    target_id: UUID
    view_types: list[str] | None = None


class RegenerateVisualReferenceRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=8000)


class VisualReferenceDecisionRequest(BaseModel):
    canonical: bool = False


class VisualReferenceRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    asset_id: UUID
    target_kind: str
    target_id: UUID
    view_type: str
    prompt: str
    provider: str
    model: str
    status: Literal["generated", "approved", "rejected"]
    is_canonical: bool
    metadata_json: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConsistencyIssue(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"


class VisualConsistencyRead(BaseModel):
    target_kind: str
    target_id: UUID
    issues: list[ConsistencyIssue] = Field(default_factory=list)
