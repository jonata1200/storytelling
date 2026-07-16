from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ArtifactStatus, ArtifactType, ProjectStatus


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=220)
    description: str | None = None


class ProjectRead(BaseModel):
    id: UUID
    title: str
    description: str | None
    status: ProjectStatus
    current_version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArtifactCreate(BaseModel):
    artifact_type: ArtifactType
    name: str = Field(min_length=1, max_length=220)
    payload: dict = Field(default_factory=dict)


class ArtifactRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_type: ArtifactType
    name: str
    status: ArtifactStatus
    locked: bool
    current_version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
