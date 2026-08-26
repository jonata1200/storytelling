from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import (
    ApprovalDecision,
    ArtifactStatus,
    ArtifactType,
    DependencyKind,
    ProjectStatus,
)

ARTIFACT_PAYLOAD_MAX_BYTES = 512 * 1024


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


class ProjectSearchRead(BaseModel):
    items: list[ProjectRead]
    total: int
    limit: int
    offset: int


class ArtifactCreate(BaseModel):
    artifact_type: ArtifactType
    name: str = Field(min_length=1, max_length=220)
    payload: dict = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _validate_payload_size(cls, value: dict) -> dict:
        import json

        serialized = json.dumps(value, default=str, ensure_ascii=True)
        if len(serialized.encode("utf-8")) > ARTIFACT_PAYLOAD_MAX_BYTES:
            raise ValueError(f"payload excede o limite de {ARTIFACT_PAYLOAD_MAX_BYTES} bytes")
        return value


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


class ProjectStatusUpdate(BaseModel):
    status: ProjectStatus


class ArtifactVersionCreate(BaseModel):
    payload: dict = Field(default_factory=dict)
    change_note: str | None = None


class ArtifactVersionRead(BaseModel):
    id: UUID
    artifact_id: UUID
    version_number: int
    payload: dict
    change_note: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApprovalCreate(BaseModel):
    artifact_version_id: UUID
    decision: ApprovalDecision
    notes: str | None = None


class ApprovalRead(BaseModel):
    id: UUID
    artifact_id: UUID
    artifact_version_id: UUID
    decision: ApprovalDecision
    notes: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArtifactDependencyCreate(BaseModel):
    upstream_artifact_id: UUID
    downstream_artifact_id: UUID
    dependency_kind: DependencyKind = DependencyKind.DERIVED_FROM


class ArtifactDependencyRead(BaseModel):
    id: UUID
    upstream_artifact_id: UUID
    downstream_artifact_id: UUID
    dependency_kind: DependencyKind

    model_config = ConfigDict(from_attributes=True)


class StaleArtifactsRead(BaseModel):
    stale_artifact_ids: list[UUID]
