from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.costs.service import CostBudgetExceededError
from app.database.session import get_session
from app.video_generation.continuous import (
    approve_continuous_video_segment,
    generate_continuous_video_segments,
    generate_next_continuous_video_segment,
    list_continuous_video_segments,
    plan_continuous_video_segments,
    regenerate_rejected_continuous_video_segment,
    reject_continuous_video_segment,
    retry_failed_continuous_video_segment,
    update_continuous_video_segment_prompt,
)
from app.video_generation.schemas import (
    ClipReviewCreate,
    ClipReviewRead,
    ContinuousVideoGenerateRequest,
    ContinuousVideoGenerationRead,
    ContinuousVideoPlanningRead,
    ContinuousVideoPlanRead,
    ContinuousVideoPlanSegmentsRequest,
    ContinuousVideoReviewRequest,
    ContinuousVideoSegmentPromptUpdate,
    ContinuousVideoSegmentRead,
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

router = APIRouter(prefix="/video/projects", tags=["video"])


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


@router.post("/{project_id}/continuous/generate", response_model=ContinuousVideoGenerationRead)
async def post_generate_continuous_video_segments(
    project_id: UUID,
    payload: ContinuousVideoGenerateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoGenerationRead:
    try:
        jobs, segments = await generate_continuous_video_segments(
            session,
            project_id,
            segment_ids=payload.segment_ids,
            provider_name=payload.provider,
            model=payload.model,
            retry_failed=payload.retry_failed,
            max_segments=payload.max_segments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ContinuousVideoGenerationRead(
        jobs=[GenerationJobRead.model_validate(job) for job in jobs],
        segments=[ContinuousVideoSegmentRead.model_validate(segment) for segment in segments],
    )


@router.get("/{project_id}/continuous/segments", response_model=list[ContinuousVideoSegmentRead])
async def get_continuous_video_segments(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ContinuousVideoSegmentRead]:
    segments = await list_continuous_video_segments(session, project_id)
    return [ContinuousVideoSegmentRead.model_validate(segment) for segment in segments]


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
    "/{project_id}/continuous/segments/{segment_id}/approve",
    response_model=ContinuousVideoSegmentRead,
)
async def post_approve_continuous_video_segment(
    project_id: UUID,
    segment_id: UUID,
    payload: ContinuousVideoReviewRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoSegmentRead:
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


@router.post("/{project_id}/continuous/generate-next", response_model=ContinuousVideoGenerationRead)
async def post_generate_next_continuous_video_segment(
    project_id: UUID,
    payload: ContinuousVideoGenerateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoGenerationRead:
    try:
        jobs, segments = await generate_next_continuous_video_segment(
            session,
            project_id,
            provider_name=payload.provider,
            model=payload.model,
            retry_failed=payload.retry_failed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ContinuousVideoGenerationRead(
        jobs=[GenerationJobRead.model_validate(job) for job in jobs],
        segments=[ContinuousVideoSegmentRead.model_validate(segment) for segment in segments],
    )


@router.post(
    "/{project_id}/continuous/segments/{segment_id}/retry",
    response_model=ContinuousVideoGenerationRead,
)
async def post_retry_failed_continuous_video_segment(
    project_id: UUID,
    segment_id: UUID,
    payload: ContinuousVideoGenerateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoGenerationRead:
    try:
        jobs, segments = await retry_failed_continuous_video_segment(
            session,
            project_id,
            segment_id,
            provider_name=payload.provider,
            model=payload.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ContinuousVideoGenerationRead(
        jobs=[GenerationJobRead.model_validate(job) for job in jobs],
        segments=[ContinuousVideoSegmentRead.model_validate(segment) for segment in segments],
    )


@router.post(
    "/{project_id}/continuous/segments/{segment_id}/regenerate",
    response_model=ContinuousVideoGenerationRead,
)
async def post_regenerate_rejected_continuous_video_segment(
    project_id: UUID,
    segment_id: UUID,
    payload: ContinuousVideoGenerateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoGenerationRead:
    try:
        jobs, segments = await regenerate_rejected_continuous_video_segment(
            session,
            project_id,
            segment_id,
            provider_name=payload.provider,
            model=payload.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ContinuousVideoGenerationRead(
        jobs=[GenerationJobRead.model_validate(job) for job in jobs],
        segments=[ContinuousVideoSegmentRead.model_validate(segment) for segment in segments],
    )


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
            payload.include_canonical_references,
        )
    except CostBudgetExceededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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
