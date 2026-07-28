from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.database.session import get_session
from app.observability.schemas import (
    OperationalEventRead,
    ProjectOperationalSummaryRead,
    ReadinessDashboardRead,
)
from app.observability.service import (
    list_project_events,
    project_operational_summary,
    readiness_dashboard,
)

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/projects/{project_id}/events", response_model=list[OperationalEventRead])
async def get_project_events(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[OperationalEventRead]:
    events = await list_project_events(session, project_id, limit)
    return [OperationalEventRead.model_validate(event) for event in events]


@router.get("/projects/{project_id}/summary", response_model=ProjectOperationalSummaryRead)
async def get_project_operational_summary(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectOperationalSummaryRead:
    return await project_operational_summary(session, project_id)


@router.get("/readiness", response_model=ReadinessDashboardRead)
async def get_readiness_dashboard(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadinessDashboardRead:
    return await readiness_dashboard(session, settings)
