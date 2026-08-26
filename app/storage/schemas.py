from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StorageFileRead(BaseModel):
    path: str
    size_bytes: int
    modified_at: datetime | None = None


class StorageProjectUsageRead(BaseModel):
    project_id: UUID
    asset_count: int = 0
    local_file_count: int = 0
    missing_file_count: int = 0
    total_bytes: int = 0
    by_kind: dict[str, int] = Field(default_factory=dict)


class StorageUsageRead(BaseModel):
    storage_backend: str = "local"
    project_count: int
    asset_count: int
    local_file_count: int
    missing_file_count: int
    total_bytes: int
    orphan_file_count: int
    orphan_total_bytes: int
    projects: list[StorageProjectUsageRead]

    model_config = ConfigDict(arbitrary_types_allowed=True)


class StorageCleanupRead(BaseModel):
    dry_run: bool
    candidate_count: int
    candidate_total_bytes: int
    deleted_count: int = 0
    deleted_total_bytes: int = 0
    skipped_count: int = 0
    files: list[StorageFileRead] = Field(default_factory=list)


class StorageReconciliationRead(BaseModel):
    project_id: UUID | None = None
    kind: str | None = None
    scanned_assets: int = 0
    local_file_count: int = 0
    missing_file_count: int = 0
    recovered_file_count: int = 0
    updated_asset_count: int = 0
    total_bytes: int = 0
