from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus, DependencyKind, ProjectStatus
from app.projects.models import Artifact, ArtifactVersion, Project, ProjectVersion
from app.projects.repository import ProjectRepository
from app.projects.schemas import ArtifactCreate, ProjectCreate
from app.projects.versioning import create_artifact_version, mark_dependents_stale
from app.workflows.models import ArtifactDependency
from app.workflows.state_machine import assert_project_transition


async def create_project(session: AsyncSession, data: ProjectCreate) -> Project:
    project = Project(title=data.title, description=data.description)
    session.add(project)
    await session.flush()

    version = ProjectVersion(
        project_id=project.id,
        version_number=1,
        snapshot={"title": project.title, "description": project.description},
        change_note="Initial project version",
    )
    session.add(version)
    await session.commit()
    await session.refresh(project)
    return project


async def list_projects(session: AsyncSession) -> list[Project]:
    return await ProjectRepository(session).list_projects()


async def rename_project(session: AsyncSession, project_id: UUID, title: str) -> Project | None:
    cleaned_title = title.strip()
    if not cleaned_title:
        raise ValueError("O nome do projeto nao pode ficar vazio")
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return None
    project.title = cleaned_title[:220]
    project.current_version += 1
    session.add(
        ProjectVersion(
            project_id=project.id,
            version_number=project.current_version,
            snapshot={"title": project.title, "description": project.description},
            change_note="Project renamed",
        )
    )
    await session.commit()
    await session.refresh(project)
    return project


async def delete_project(session: AsyncSession, project_id: UUID) -> bool:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return False
    project.deleted_at = datetime.now(UTC)
    await session.commit()
    return True


async def create_artifact(
    session: AsyncSession, project_id: UUID, data: ArtifactCreate
) -> Artifact | None:
    project = await session.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        return None

    artifact = Artifact(
        project_id=project_id,
        artifact_type=data.artifact_type,
        name=data.name,
        status=ArtifactStatus.READY_FOR_REVIEW if data.payload else ArtifactStatus.PENDING,
    )
    session.add(artifact)
    await session.flush()
    session.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version_number=1,
            payload=data.payload,
            change_note="Initial artifact version",
        )
    )
    await session.commit()
    await session.refresh(artifact)
    return artifact


async def transition_project_status(
    session: AsyncSession, project_id: UUID, target_status: ProjectStatus
) -> Project | None:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return None
    assert_project_transition(project.status, target_status)
    project.status = target_status
    await session.commit()
    await session.refresh(project)
    return project


async def add_artifact_version(
    session: AsyncSession,
    artifact_id: UUID,
    payload: dict,
    change_note: str | None = None,
) -> ArtifactVersion | None:
    artifact = await ProjectRepository(session).get_artifact(artifact_id)
    if artifact is None:
        return None
    version = await create_artifact_version(session, artifact, payload, change_note)
    await session.commit()
    await session.refresh(version)
    return version


async def add_artifact_dependency(
    session: AsyncSession,
    upstream_artifact_id: UUID,
    downstream_artifact_id: UUID,
    dependency_kind: DependencyKind,
) -> ArtifactDependency | None:
    repository = ProjectRepository(session)
    upstream = await repository.get_artifact(upstream_artifact_id)
    downstream = await repository.get_artifact(downstream_artifact_id)
    if upstream is None or downstream is None:
        return None
    if upstream.project_id != downstream.project_id or upstream.id == downstream.id:
        return None

    dependency = ArtifactDependency(
        upstream_artifact_id=upstream_artifact_id,
        downstream_artifact_id=downstream_artifact_id,
        dependency_kind=dependency_kind,
    )
    session.add(dependency)
    await session.commit()
    await session.refresh(dependency)
    return dependency


async def stale_dependents_for_artifact(session: AsyncSession, artifact_id: UUID) -> set[UUID]:
    stale_ids = await mark_dependents_stale(session, {artifact_id})
    await session.commit()
    return stale_ids
