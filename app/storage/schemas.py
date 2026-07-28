from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StorageFileRead(BaseModel):
    path: str
    size_bytes: int


class StorageProjectUsageRead(BaseModel):
    project_id: UUID
    asset_count: int = 0
    local_file_count: int = 0
    missing_file_count: int = 0
    total_bytes: int = 0
    by_kind: dict[str, int] = Field(default_factory=dict)


class StorageUsageRead(BaseModel):
    storage_root: Path
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
