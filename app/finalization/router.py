from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dubbing.schemas import DubbingJobRead, DubbingStartRequest
from app.dubbing.service import (
    list_dubbing_jobs,
    refresh_dubbing_job,
    start_dubbing_job,
    start_project_dubbing,
)
from app.finalization.schemas import (
    ExportRead,
    ExportRequest,
    FinalTimelineRequest,
)
from app.finalization.service import (
    create_final_timeline,
    export_timeline,
)
from app.storyboards.models import TimelineItem
from app.storyboards.schemas import TimelineItemRead, TimelineRead

router = APIRouter(prefix="/finalization/projects", tags=["finalization"])


@router.post("/{project_id}/timeline/final", response_model=TimelineRead)
async def post_final_timeline(
    project_id: UUID,
    payload: FinalTimelineRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TimelineRead:
    try:
        timeline = await create_final_timeline(session, project_id, payload.animatic_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if timeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project or video clips not found",
        )
    result = await session.execute(
        select(TimelineItem)
        .where(TimelineItem.timeline_id == timeline.id)
        .order_by(TimelineItem.order_index)
    )
    timeline_read = TimelineRead.model_validate(timeline)
    timeline_read.items = [TimelineItemRead.model_validate(item) for item in result.scalars()]
    return timeline_read


@router.post("/{project_id}/exports", response_model=ExportRead)
async def post_export(
    project_id: UUID,
    payload: ExportRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ExportRead:
    export = await export_timeline(
        session,
        project_id,
        payload.timeline_id,
        payload.subtitle_track_id,
        payload.fps,
        payload.bitrate,
        payload.embed_subtitles,
        payload.resolution,
        payload.video_codec,
        payload.audio_codec,
    )
    if export is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project, timeline, or subtitle track not found",
        )
    return ExportRead.model_validate(export)


@router.post("/{project_id}/exports/{export_id}/dubbing", response_model=DubbingJobRead)
async def post_export_dubbing(
    project_id: UUID,
    export_id: UUID,
    payload: DubbingStartRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DubbingJobRead:
    try:
        job = await start_dubbing_job(
            session,
            project_id,
            export_id,
            source_language=payload.source_language,
            target_language=payload.target_language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    return DubbingJobRead.model_validate(job)


@router.post("/{project_id}/dubbing", response_model=DubbingJobRead)
async def post_project_dubbing(
    project_id: UUID,
    payload: DubbingStartRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DubbingJobRead:
    try:
        job = await start_project_dubbing(
            session,
            project_id,
            source_language=payload.source_language,
            target_language=payload.target_language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return DubbingJobRead.model_validate(job)


@router.get("/{project_id}/exports/{export_id}/dubbing", response_model=list[DubbingJobRead])
async def get_export_dubbing_jobs(
    project_id: UUID,
    export_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DubbingJobRead]:
    jobs = await list_dubbing_jobs(session, project_id, export_id)
    return [DubbingJobRead.model_validate(job) for job in jobs]


@router.get("/{project_id}/dubbing/{job_id}", response_model=DubbingJobRead)
async def get_dubbing_job(
    project_id: UUID,
    job_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DubbingJobRead:
    job = await refresh_dubbing_job(
        session,
        project_id,
        job_id,
        download_when_ready=False,
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dubbing job not found")
    return DubbingJobRead.model_validate(job)


@router.post("/{project_id}/dubbing/{job_id}/poll", response_model=DubbingJobRead)
async def post_dubbing_poll(
    project_id: UUID,
    job_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DubbingJobRead:
    try:
        job = await refresh_dubbing_job(session, project_id, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dubbing job not found")
    return DubbingJobRead.model_validate(job)
