from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.jobs.schemas import JobCreate, JobRead
from app.jobs.service import enqueue_project_step, get_job, list_project_jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/projects/{project_id}", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
async def post_project_job(
    project_id: UUID,
    payload: JobCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JobRead:
    try:
        job = await enqueue_project_step(session, project_id, payload.step, payload.payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return JobRead.model_validate(job)


@router.get("/projects/{project_id}", response_model=list[JobRead])
async def get_project_jobs(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[JobRead]:
    return [JobRead.model_validate(job) for job in await list_project_jobs(session, project_id)]


@router.get("/{job_id}", response_model=JobRead)
async def get_project_job(
    job_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JobRead:
    job = await get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobRead.model_validate(job)
