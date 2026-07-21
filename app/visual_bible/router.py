from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_basic_auth
from app.database.session import get_session
from app.projects.repository import ProjectRepository
from app.visual_bible.models import Character, Location, Prop
from app.visual_bible.schemas import (
    CharacterRead,
    GenerateVisualBibleRequest,
    GenerateVisualReferencesRequest,
    LocationRead,
    PropRead,
    VisualBibleRead,
    VisualConsistencyRead,
    VisualReferenceRead,
)
from app.visual_bible.service import (
    check_visual_consistency,
    generate_visual_bible,
    generate_visual_references,
)

router = APIRouter(
    prefix="/visual-bible/projects",
    tags=["visual-bible"],
    dependencies=[Depends(require_basic_auth)],
)


@router.post("/{project_id}/generate", response_model=VisualBibleRead)
async def post_generate_visual_bible(
    project_id: UUID,
    payload: GenerateVisualBibleRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VisualBibleRead:
    try:
        result = await generate_visual_bible(session, project_id, payload.story_bible_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project or Story Bible not found",
        )
    characters, locations, props = result
    return VisualBibleRead(
        characters=[CharacterRead.model_validate(character) for character in characters],
        locations=[LocationRead.model_validate(location) for location in locations],
        props=[PropRead.model_validate(prop) for prop in props],
    )


@router.get("/{project_id}/characters", response_model=list[CharacterRead])
async def get_characters(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CharacterRead]:
    if await ProjectRepository(session).get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    result = await session.execute(
        select(Character).where(Character.project_id == project_id).order_by(Character.created_at)
    )
    return [CharacterRead.model_validate(character) for character in result.scalars()]


@router.get("/{project_id}/locations", response_model=list[LocationRead])
async def get_locations(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[LocationRead]:
    if await ProjectRepository(session).get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    result = await session.execute(
        select(Location).where(Location.project_id == project_id).order_by(Location.created_at)
    )
    return [LocationRead.model_validate(location) for location in result.scalars()]


@router.get("/{project_id}/props", response_model=list[PropRead])
async def get_props(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PropRead]:
    if await ProjectRepository(session).get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    result = await session.execute(
        select(Prop).where(Prop.project_id == project_id).order_by(Prop.created_at)
    )
    return [PropRead.model_validate(prop) for prop in result.scalars()]


@router.post("/{project_id}/references/generate", response_model=list[VisualReferenceRead])
async def post_generate_visual_references(
    project_id: UUID,
    payload: GenerateVisualReferencesRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[VisualReferenceRead]:
    try:
        references = await generate_visual_references(
            session,
            project_id,
            payload.target_kind,
            payload.target_id,
            payload.view_types,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Nao foi possivel gerar referencia visual: {exc}",
        ) from exc
    if references is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visual target not found")
    return [VisualReferenceRead.model_validate(reference) for reference in references]


@router.get(
    "/{project_id}/consistency/{target_kind}/{target_id}",
    response_model=VisualConsistencyRead,
)
async def get_visual_consistency(
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VisualConsistencyRead:
    if target_kind not in {"character", "location", "prop"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid target kind")
    issues = await check_visual_consistency(session, project_id, target_kind, target_id)
    if issues is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visual target not found")
    return VisualConsistencyRead(target_kind=target_kind, target_id=target_id, issues=issues)
