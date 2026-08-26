from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.video_generation.continuous import (
    approve_continuous_video_segment,
    delete_all_continuous_video_segments,
    list_continuous_video_segments,
    plan_continuous_video_segments,
    prepare_continuous_video_package,
    reject_continuous_video_segment,
    update_continuous_video_segment_prompt,
)
from app.video_generation.schemas import (
    ContinuousVideoPlanningRead,
    ContinuousVideoPlanRead,
    ContinuousVideoPlanSegmentsRequest,
    ContinuousVideoPreparationRead,
    ContinuousVideoPrepareRequest,
    ContinuousVideoReviewRequest,
    ContinuousVideoSegmentPromptUpdate,
    ContinuousVideoSegmentRead,
    GenerationJobRead,
    VideoClipRead,
)
from app.video_generation.service import (
    get_job_status,
    list_video_clips,
)

router = APIRouter(prefix="/video/projects", tags=["video"])


@router.post("/{project_id}/continuous/plan", response_model=ContinuousVideoPlanningRead)
async def post_plan_continuous_video_segments(
    project_id: UUID,
    payload: ContinuousVideoPlanSegmentsRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoPlanningRead:
    try:
        plan, segments, validation_errors = await plan_continuous_video_segments(
            session,
            project_id,
            segment_duration_seconds=payload.segment_duration_seconds,
            provider=payload.provider,
            model=payload.model,
            replace_existing=payload.replace_existing,
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ContinuousVideoPlanningRead(
        plan=ContinuousVideoPlanRead.model_validate(plan),
        segments=[ContinuousVideoSegmentRead.model_validate(segment) for segment in segments],
        validation_errors=validation_errors,
    )


@router.post("/{project_id}/continuous/prepare", response_model=ContinuousVideoPreparationRead)
async def post_prepare_continuous_video_package(
    project_id: UUID,
    payload: ContinuousVideoPrepareRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoPreparationRead:
    """Prepara o pacote (prompt + frame inicial + frame final) de vídeo."""
    try:
        segments, validation_errors = await prepare_continuous_video_package(
            session,
            project_id,
            segment_ids=payload.segment_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ContinuousVideoPreparationRead(
        segments=[ContinuousVideoSegmentRead.model_validate(segment) for segment in segments],
        validation_errors=validation_errors,
    )


@router.get("/{project_id}/continuous/segments", response_model=list[ContinuousVideoSegmentRead])
async def get_continuous_video_segments(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ContinuousVideoSegmentRead]:
    segments = await list_continuous_video_segments(session, project_id)
    return [ContinuousVideoSegmentRead.model_validate(segment) for segment in segments]


@router.delete("/{project_id}/continuous/segments")
async def delete_continuous_video_segments(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, int]:
    """Deleta todos os segmentos, prompts e conteudos de producao de video."""
    count = await delete_all_continuous_video_segments(session, project_id)
    await session.commit()
    return {"deleted": count}


@router.patch(
    "/{project_id}/continuous/segments/{segment_id}",
    response_model=ContinuousVideoSegmentRead,
)
async def patch_continuous_video_segment_prompt(
    project_id: UUID,
    segment_id: UUID,
    payload: ContinuousVideoSegmentPromptUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoSegmentRead:
    try:
        segment = await update_continuous_video_segment_prompt(
            session,
            project_id,
            segment_id,
            prompt=payload.prompt,
            title=payload.title,
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    return ContinuousVideoSegmentRead.model_validate(segment)


@router.post(
    "/{project_id}/continuous/segments/{segment_id}/done",
    response_model=ContinuousVideoSegmentRead,
)
@router.post(
    "/{project_id}/continuous/segments/{segment_id}/approve",
    response_model=ContinuousVideoSegmentRead,
    include_in_schema=False,
)
async def post_approve_continuous_video_segment(
    project_id: UUID,
    segment_id: UUID,
    payload: ContinuousVideoReviewRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoSegmentRead:
    """Conclui o segmento: o usuário criou o vídeo manualmente e marcou como feito."""
    try:
        segment = await approve_continuous_video_segment(
            session,
            project_id,
            segment_id,
            note=payload.note,
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    return ContinuousVideoSegmentRead.model_validate(segment)


@router.post(
    "/{project_id}/continuous/segments/{segment_id}/reject",
    response_model=ContinuousVideoSegmentRead,
)
async def post_reject_continuous_video_segment(
    project_id: UUID,
    segment_id: UUID,
    payload: ContinuousVideoReviewRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoSegmentRead:
    try:
        segment = await reject_continuous_video_segment(
            session,
            project_id,
            segment_id,
            note=payload.note,
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    return ContinuousVideoSegmentRead.model_validate(segment)


@router.get("/{project_id}/clips", response_model=list[VideoClipRead])
async def get_video_clips(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[VideoClipRead]:
    clips = await list_video_clips(session, project_id)
    return [VideoClipRead.model_validate(clip) for clip in clips]


@router.get("/{project_id}/jobs/{job_id}", response_model=GenerationJobRead)
async def get_video_job(
    project_id: UUID,
    job_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GenerationJobRead:
    job = await get_job_status(session, job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return GenerationJobRead.model_validate(job)
