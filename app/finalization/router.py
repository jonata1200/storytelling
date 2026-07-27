from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.finalization.schemas import (
    ExportRead,
    ExportRequest,
    FinalTimelineRequest,
    GenerateNarrationRequest,
    SubtitleRequest,
    SubtitleTrackRead,
)
from app.finalization.service import (
    create_final_timeline,
    export_timeline,
    generate_subtitles,
    synthesize_narration,
)
from app.storyboards.models import TimelineItem
from app.storyboards.schemas import AudioTrackRead, TimelineItemRead, TimelineRead

router = APIRouter(prefix="/finalization/projects", tags=["finalization"])


@router.post("/{project_id}/narration/generate", response_model=AudioTrackRead)
async def post_generate_narration(
    project_id: UUID,
    payload: GenerateNarrationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AudioTrackRead:
    try:
        track = await synthesize_narration(
            session, project_id, payload.audio_track_id, payload.voice_profile_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if track is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project or audio track not found",
        )
    return AudioTrackRead.model_validate(track)


@router.post("/{project_id}/subtitles/generate", response_model=SubtitleTrackRead)
async def post_generate_subtitles(
    project_id: UUID,
    payload: SubtitleRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubtitleTrackRead:
    subtitle = await generate_subtitles(
        session, project_id, payload.audio_track_id, payload.language
    )
    if subtitle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project or audio track not found",
        )
    return SubtitleTrackRead.model_validate(subtitle)


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
