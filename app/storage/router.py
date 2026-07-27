from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.storage.schemas import StorageCleanupRead, StorageFileRead, StorageUsageRead
from app.storage.service import (
    cleanup_orphan_storage_files,
    list_orphan_storage_files,
    storage_usage_summary,
)

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/usage", response_model=StorageUsageRead)
async def get_storage_usage(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StorageUsageRead:
    return await storage_usage_summary(session)


@router.get("/projects/{project_id}/usage", response_model=StorageUsageRead)
async def get_project_storage_usage(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StorageUsageRead:
    return await storage_usage_summary(session, project_id)


@router.get("/orphans", response_model=list[StorageFileRead])
async def get_storage_orphans(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[StorageFileRead]:
    return await list_orphan_storage_files(session)


@router.post("/orphans/cleanup", response_model=StorageCleanupRead)
async def post_storage_orphan_cleanup(
    session: Annotated[AsyncSession, Depends(get_session)],
    dry_run: Annotated[bool, Query()] = True,
) -> StorageCleanupRead:
    return await cleanup_orphan_storage_files(session, dry_run=dry_run)
