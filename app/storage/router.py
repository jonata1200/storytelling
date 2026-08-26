from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.auth import verify_api_token
from app.database.session import get_session
from app.storage.bridge_job_lifecycle import (
    BridgeJobCleanupReport,
    prune_finished_bridge_jobs,
)
from app.storage.schemas import (
    StorageCleanupRead,
    StorageFileRead,
    StorageReconciliationRead,
    StorageUsageRead,
)
from app.storage.service import (
    cleanup_orphan_storage_files,
    list_orphan_storage_files,
    reconcile_local_storage,
    storage_usage_summary,
)

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/usage", response_model=StorageUsageRead)
async def get_storage_usage(
    session: Annotated[AsyncSession, Depends(get_session)],
    include_orphans: Annotated[bool, Query()] = False,
) -> StorageUsageRead:
    return await storage_usage_summary(session, include_orphans=include_orphans)


@router.get("/projects/{project_id}/usage", response_model=StorageUsageRead)
async def get_project_storage_usage(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    include_orphans: Annotated[bool, Query()] = False,
) -> StorageUsageRead:
    return await storage_usage_summary(
        session,
        project_id,
        include_orphans=include_orphans,
    )


@router.post("/reconcile", response_model=StorageReconciliationRead)
async def post_storage_reconciliation(
    session: Annotated[AsyncSession, Depends(get_session)],
    kind: Annotated[str | None, Query(max_length=40)] = None,
) -> StorageReconciliationRead:
    try:
        summary = await reconcile_local_storage(session, kind=kind)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return summary


@router.post("/projects/{project_id}/reconcile", response_model=StorageReconciliationRead)
async def post_project_storage_reconciliation(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    kind: Annotated[str | None, Query(max_length=40)] = None,
) -> StorageReconciliationRead:
    try:
        summary = await reconcile_local_storage(session, project_id=project_id, kind=kind)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return summary


@router.get("/orphans", response_model=list[StorageFileRead])
async def get_storage_orphans(
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: Annotated[UUID | None, Query()] = None,
    kind: Annotated[str | None, Query(max_length=40)] = None,
    older_than_days: Annotated[int | None, Query(ge=0)] = None,
) -> list[StorageFileRead]:
    try:
        return await list_orphan_storage_files(
            session,
            project_id=project_id,
            kind=kind,
            older_than_days=older_than_days,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post(
    "/orphans/cleanup",
    response_model=StorageCleanupRead,
    dependencies=[Depends(verify_api_token)],
)
async def post_storage_orphan_cleanup(
    session: Annotated[AsyncSession, Depends(get_session)],
    dry_run: Annotated[bool, Query()] = True,
    confirm: Annotated[bool, Query()] = False,
    project_id: Annotated[UUID | None, Query()] = None,
    kind: Annotated[str | None, Query(max_length=40)] = None,
    older_than_days: Annotated[int | None, Query(ge=0)] = None,
) -> StorageCleanupRead:
    try:
        return await cleanup_orphan_storage_files(
            session,
            dry_run=dry_run,
            confirm=confirm,
            project_id=project_id,
            kind=kind,
            older_than_days=older_than_days,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


class BridgeJobCleanupRead(BaseModel):
    dry_run: bool
    removed_job_dirs: list[str] = Field(default_factory=list)
    removed_bytes: int = 0
    kept_pending_jobs: int = 0


@router.post(
    "/bridge-jobs/cleanup",
    response_model=BridgeJobCleanupRead,
    dependencies=[Depends(verify_api_token)],
)
async def post_bridge_job_cleanup(
    dry_run: Annotated[bool, Query()] = True,
    confirm: Annotated[bool, Query()] = False,
) -> BridgeJobCleanupRead:
    """Remove diretórios de job do bridge terminados + expirados (ARQ-02)."""
    if not dry_run and not confirm:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cleanup destrutivo exige confirmacao explicita.",
        )
    jobs_root = get_settings().local_storage_path / "bridge_jobs" / "video"
    report: BridgeJobCleanupReport = prune_finished_bridge_jobs(jobs_root, dry_run=dry_run)
    return BridgeJobCleanupRead(
        dry_run=dry_run,
        removed_job_dirs=report.removed_job_dirs,
        removed_bytes=report.removed_bytes,
        kept_pending_jobs=report.kept_pending_jobs,
    )
