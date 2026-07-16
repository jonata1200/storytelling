from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AssetKind


class AssetCreate(BaseModel):
    project_id: UUID
    artifact_id: UUID | None = None
    kind: AssetKind
    name: str = Field(min_length=1, max_length=220)
    storage_uri: str = Field(min_length=1, max_length=1024)
    content_type: str | None = None
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    metadata_json: dict = Field(default_factory=dict)


class AssetRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID | None
    kind: AssetKind
    name: str
    storage_uri: str
    content_type: str | None
    sha256: str | None
    current_version: int
    metadata_json: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
