from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus
from app.projects.models import Artifact, ArtifactVersion, Project, ProjectVersion
from app.projects.schemas import ArtifactCreate, ProjectCreate


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
    result = await session.execute(
        select(Project).where(Project.deleted_at.is_(None)).order_by(Project.created_at.desc())
    )
    return list(result.scalars())


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
