from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GenerateVisualBibleRequest(BaseModel):
    script_id: UUID


class CharacterRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    name: str
    role: str
    canonical_profile: dict
    character_fingerprint: dict
    current_version: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LocationRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    name: str
    description: str
    canonical_profile: dict
    current_version: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VisualBibleRead(BaseModel):
    characters: list[CharacterRead]
    locations: list[LocationRead]


class GenerateVisualReferencesRequest(BaseModel):
    target_kind: Literal["character", "location"]
    target_id: UUID
    view_types: list[str] | None = None


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
