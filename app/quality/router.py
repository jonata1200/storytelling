from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_basic_auth
from app.database.session import get_session
from app.quality.schemas import (
    AcceptContinuityIssueRequest,
    ContinuityBuildRead,
    ContinuityIssueRead,
    ObservabilitySummaryRead,
    QualityCheckRead,
    SecurityScanRead,
    SecurityScanRequest,
)
from app.quality.security import security_scan_text
from app.quality.service import (
    accept_continuity_issue,
    build_continuity_ledger,
    list_open_continuity_issues,
    observability_summary,
    run_quality_check,
)

router = APIRouter(
    prefix="/quality/projects",
    tags=["quality"],
    dependencies=[Depends(require_basic_auth)],
)


@router.post("/{project_id}/continuity/build", response_model=ContinuityBuildRead)
async def post_build_continuity(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuityBuildRead:
    result = await build_continuity_ledger(session, project_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    states, issues = result
    return ContinuityBuildRead(
        states=[item for item in states],
        issues=[item for item in issues],
    )


@router.get("/{project_id}/continuity/issues", response_model=list[ContinuityIssueRead])
async def get_continuity_issues(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ContinuityIssueRead]:
    issues = await list_open_continuity_issues(session, project_id)
    return [ContinuityIssueRead.model_validate(issue) for issue in issues]


@router.post(
    "/{project_id}/continuity/issues/{issue_id}/accept",
    response_model=ContinuityIssueRead,
)
async def post_accept_continuity_issue(
    project_id: UUID,
    issue_id: UUID,
    payload: AcceptContinuityIssueRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuityIssueRead:
    issue = await accept_continuity_issue(session, project_id, issue_id, payload.reason)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    return ContinuityIssueRead.model_validate(issue)


@router.post("/{project_id}/checks/run", response_model=QualityCheckRead)
async def post_run_quality_check(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QualityCheckRead:
    check = await run_quality_check(session, project_id)
    if check is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return QualityCheckRead.model_validate(check)


@router.get("/{project_id}/observability", response_model=ObservabilitySummaryRead)
async def get_observability_summary(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ObservabilitySummaryRead:
    summary = await observability_summary(session, project_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ObservabilitySummaryRead(**summary)


security_router = APIRouter(
    prefix="/quality",
    tags=["quality"],
    dependencies=[Depends(require_basic_auth)],
)


@security_router.post("/security/scan", response_model=SecurityScanRead)
async def post_security_scan(payload: SecurityScanRequest) -> SecurityScanRead:
    return SecurityScanRead(**security_scan_text(payload.text))
