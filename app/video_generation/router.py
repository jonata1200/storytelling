from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_basic_auth
from app.database.session import get_session
from app.video_generation.schemas import (
    ClipReviewCreate,
    ClipReviewRead,
    GenerateVideoClipsRequest,
    GenerationJobRead,
    VideoClipRead,
    VideoCostEstimateRead,
    VideoCostEstimateRequest,
    VideoGenerationBatchRead,
)
from app.video_generation.service import (
    estimate_video_batch_cost,
    generate_video_clips,
    get_job_status,
    list_video_clips,
    review_clip,
)

router = APIRouter(
    prefix="/video/projects",
    tags=["video"],
    dependencies=[Depends(require_basic_auth)],
)


@router.post("/{project_id}/cost-estimate", response_model=VideoCostEstimateRead)
async def post_video_cost_estimate(
    project_id: UUID,
    payload: VideoCostEstimateRequest,
) -> VideoCostEstimateRead:
    _ = project_id
    estimate = await estimate_video_batch_cost(
        payload.clip_count,
        payload.duration_seconds,
        payload.unit_cost_per_second,
    )
    return VideoCostEstimateRead(**estimate)


@router.post("/{project_id}/clips/generate", response_model=VideoGenerationBatchRead)
async def post_generate_video_clips(
    project_id: UUID,
    payload: GenerateVideoClipsRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VideoGenerationBatchRead:
    try:
        result = await generate_video_clips(
            session,
            project_id,
            payload.storyboard_frame_ids,
            payload.variants_per_frame,
            payload.provider,
            payload.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    jobs, clips = result
    return VideoGenerationBatchRead(
        jobs=[GenerationJobRead.model_validate(job) for job in jobs],
        clips=[VideoClipRead.model_validate(clip) for clip in clips],
    )


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


@router.post("/{project_id}/clips/{clip_id}/review", response_model=ClipReviewRead)
async def post_clip_review(
    project_id: UUID,
    clip_id: UUID,
    payload: ClipReviewCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClipReviewRead:
    review = await review_clip(
        session, project_id, clip_id, payload.decision, payload.notes, payload.selected
    )
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found")
    return ClipReviewRead.model_validate(review)
