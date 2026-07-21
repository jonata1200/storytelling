from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_basic_auth
from app.database.session import get_session
from app.storytelling.models import Shot
from app.storytelling.schemas import (
    BriefingCreate,
    BriefingRead,
    GenerateScenesRequest,
    GenerateScriptRequest,
    SceneRead,
    ScriptRead,
    ShotRead,
    StoryIdeaRead,
)
from app.storytelling.service import (
    GenerationOutputError,
    create_briefing,
    generate_scenes_and_shots,
    generate_script,
    generate_story_ideas,
    list_story_ideas,
)

router = APIRouter(
    prefix="/storytelling/projects",
    tags=["storytelling"],
    dependencies=[Depends(require_basic_auth)],
)


@router.post(
    "/{project_id}/briefing",
    response_model=BriefingRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_briefing(
    project_id: UUID,
    payload: BriefingCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BriefingRead:
    briefing = await create_briefing(session, project_id, payload)
    if briefing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return BriefingRead.model_validate(briefing)


@router.post("/{project_id}/ideas/generate", response_model=list[StoryIdeaRead])
async def post_generate_ideas(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[StoryIdeaRead]:
    try:
        ideas = await generate_story_ideas(session, project_id)
    except GenerationOutputError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    if ideas is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project or briefing not found",
        )
    return [StoryIdeaRead.model_validate(idea) for idea in ideas]


@router.get("/{project_id}/ideas", response_model=list[StoryIdeaRead])
async def get_ideas(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[StoryIdeaRead]:
    ideas = await list_story_ideas(session, project_id)
    return [StoryIdeaRead.model_validate(idea) for idea in ideas]


@router.post("/{project_id}/script/generate", response_model=ScriptRead)
async def post_generate_script(
    project_id: UUID,
    payload: GenerateScriptRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScriptRead:
    try:
        script = await generate_script(session, project_id, payload.story_idea_id)
    except GenerationOutputError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    if script is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project, briefing, or story idea not found",
        )
    return ScriptRead.model_validate(script)


@router.post("/{project_id}/scenes/generate", response_model=list[SceneRead])
async def post_generate_scenes(
    project_id: UUID,
    payload: GenerateScenesRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SceneRead]:
    try:
        scenes = await generate_scenes_and_shots(session, project_id, payload.script_id)
    except GenerationOutputError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    if scenes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project or script not found",
        )

    scene_reads: list[SceneRead] = []
    for scene in scenes:
        result = await session.execute(
            select(Shot).where(Shot.scene_id == scene.id).order_by(Shot.shot_number)
        )
        shots = [ShotRead.model_validate(shot) for shot in result.scalars()]
        scene_read = SceneRead.model_validate(scene)
        scene_read.shots = shots
        scene_reads.append(scene_read)
    return scene_reads
