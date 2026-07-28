from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.service import record_approval
from app.database.session import get_session
from app.projects.repository import ProjectRepository
from app.projects.schemas import (
    ApprovalCreate,
    ApprovalRead,
    ArtifactCreate,
    ArtifactDependencyCreate,
    ArtifactDependencyRead,
    ArtifactRead,
    ArtifactVersionCreate,
    ArtifactVersionRead,
    ProjectCreate,
    ProjectRead,
    ProjectStatusUpdate,
    StaleArtifactsRead,
)
from app.projects.service import (
    add_artifact_dependency,
    add_artifact_version,
    create_artifact,
    create_project,
    list_projects,
    stale_dependents_for_artifact,
    transition_project_status,
)

router = APIRouter(prefix="/projects", tags=["projects"])


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


@router.patch("/{project_id}/status", response_model=ProjectRead)
async def patch_project_status(
    project_id: UUID,
    payload: ProjectStatusUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectRead:
    try:
        project = await transition_project_status(session, project_id, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectRead.model_validate(project)


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


@router.post(
    "/{project_id}/artifacts/{artifact_id}/versions",
    response_model=ArtifactVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_artifact_version(
    project_id: UUID,
    artifact_id: UUID,
    payload: ArtifactVersionCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ArtifactVersionRead:
    artifact = await ProjectRepository(session).get_artifact(artifact_id)
    if artifact is None or artifact.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    try:
        version = await add_artifact_version(
            session, artifact_id, payload.payload, payload.change_note
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return ArtifactVersionRead.model_validate(version)


@router.post(
    "/artifacts/{artifact_id}/approvals",
    response_model=ApprovalRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_artifact_approval(
    artifact_id: UUID,
    payload: ApprovalCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApprovalRead:
    repository = ProjectRepository(session)
    artifact = await repository.get_artifact(artifact_id)
    artifact_version = await repository.get_artifact_version(payload.artifact_version_id)
    if artifact is None or artifact_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    try:
        approval = await record_approval(
            session,
            artifact,
            artifact_version,
            payload.decision,
            payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(approval)
    return ApprovalRead.model_validate(approval)


@router.post(
    "/artifact-dependencies",
    response_model=ArtifactDependencyRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_artifact_dependency(
    payload: ArtifactDependencyCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ArtifactDependencyRead:
    dependency = await add_artifact_dependency(
        session,
        payload.upstream_artifact_id,
        payload.downstream_artifact_id,
        payload.dependency_kind,
    )
    if dependency is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return ArtifactDependencyRead.model_validate(dependency)


@router.post("/artifacts/{artifact_id}/mark-dependents-stale", response_model=StaleArtifactsRead)
async def post_mark_dependents_stale(
    artifact_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StaleArtifactsRead:
    artifact = await ProjectRepository(session).get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    stale_ids = await stale_dependents_for_artifact(session, artifact_id)
    return StaleArtifactsRead(stale_artifact_ids=sorted(stale_ids, key=str))
