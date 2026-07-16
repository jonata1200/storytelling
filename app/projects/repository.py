from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects.models import Artifact, ArtifactVersion, Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_project(self, project_id: UUID) -> Project | None:
        project = await self.session.get(Project, project_id)
        if project is None or project.deleted_at is not None:
            return None
        return project

    async def list_projects(self) -> list[Project]:
        result = await self.session.execute(
            select(Project).where(Project.deleted_at.is_(None)).order_by(Project.created_at.desc())
        )
        return list(result.scalars())

    async def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        artifact = await self.session.get(Artifact, artifact_id)
        if artifact is None or artifact.deleted_at is not None:
            return None
        return artifact

    async def get_artifact_version(self, version_id: UUID) -> ArtifactVersion | None:
        version = await self.session.get(ArtifactVersion, version_id)
        if version is None or version.deleted_at is not None:
            return None
        return version
