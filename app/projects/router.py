from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_basic_auth
from app.database.session import get_session
from app.projects.schemas import ArtifactCreate, ArtifactRead, ProjectCreate, ProjectRead
from app.projects.service import create_artifact, create_project, list_projects

router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    dependencies=[Depends(require_basic_auth)],
)


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def post_project(
    payload: ProjectCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectRead:
    project = await create_project(session, payload)
    return ProjectRead.model_validate(project)


@router.get("", response_model=list[ProjectRead])
async def get_projects(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ProjectRead]:
    projects = await list_projects(session)
    return [ProjectRead.model_validate(project) for project in projects]


@router.post(
    "/{project_id}/artifacts",
    response_model=ArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_artifact(
    project_id: UUID,
    payload: ArtifactCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ArtifactRead:
    artifact = await create_artifact(session, project_id, payload)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ArtifactRead.model_validate(artifact)
