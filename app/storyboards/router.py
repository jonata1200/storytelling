from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_basic_auth
from app.database.session import get_session
from app.storyboards.schemas import (
    AnimaticBundleRead,
    AnimaticRead,
    AudioTrackRead,
    GenerateAnimaticRequest,
    GenerateStoryboardsRequest,
    StoryboardFrameRead,
    TimelineItemRead,
    TimelineRead,
)
from app.storyboards.service import (
    generate_animatic_bundle,
    generate_storyboard_frames,
    list_storyboard_frames,
)

router = APIRouter(
    prefix="/storyboards/projects",
    tags=["storyboards"],
    dependencies=[Depends(require_basic_auth)],
)


@router.post("/{project_id}/generate", response_model=list[StoryboardFrameRead])
async def post_generate_storyboards(
    project_id: UUID,
    payload: GenerateStoryboardsRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[StoryboardFrameRead]:
    try:
        frames = await generate_storyboard_frames(session, project_id, payload.script_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if frames is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project or script not found",
        )
    return [StoryboardFrameRead.model_validate(frame) for frame in frames]


@router.get("/{project_id}/frames", response_model=list[StoryboardFrameRead])
async def get_storyboard_frames(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[StoryboardFrameRead]:
    frames = await list_storyboard_frames(session, project_id)
    return [StoryboardFrameRead.model_validate(frame) for frame in frames]


@router.post("/{project_id}/animatic/generate", response_model=AnimaticBundleRead)
async def post_generate_animatic(
    project_id: UUID,
    payload: GenerateAnimaticRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnimaticBundleRead:
    try:
        bundle = await generate_animatic_bundle(session, project_id, payload.script_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project, script, shots, or storyboard frames not found",
        )
    audio_track, animatic, timeline, items = bundle
    timeline_read = TimelineRead.model_validate(timeline)
    timeline_read.items = [TimelineItemRead.model_validate(item) for item in items]
    return AnimaticBundleRead(
        audio_track=AudioTrackRead.model_validate(audio_track),
        animatic=AnimaticRead.model_validate(animatic),
        timeline=timeline_read,
    )
