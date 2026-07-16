from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus
from app.projects.models import Artifact, ArtifactVersion
from app.workflows.dependencies import collect_dependent_artifacts
from app.workflows.models import ArtifactDependency


async def create_artifact_version(
    session: AsyncSession,
    artifact: Artifact,
    payload: dict,
    change_note: str | None = None,
) -> ArtifactVersion:
    if artifact.locked:
        raise ValueError("Locked artifacts cannot be changed automatically")

    next_version = artifact.current_version + 1
    version = ArtifactVersion(
        artifact_id=artifact.id,
        version_number=next_version,
        payload=payload,
        change_note=change_note,
    )
    artifact.current_version = next_version
    artifact.status = ArtifactStatus.READY_FOR_REVIEW
    session.add(version)
    await mark_dependents_stale(session, {artifact.id})
    return version


async def mark_dependents_stale(
    session: AsyncSession, changed_artifact_ids: set[UUID]
) -> set[UUID]:
    dependency_rows = await session.execute(
        select(
            ArtifactDependency.upstream_artifact_id,
            ArtifactDependency.downstream_artifact_id,
        )
    )
    edges = [(row[0], row[1]) for row in dependency_rows.all()]

    artifact_rows = await session.execute(select(Artifact.id, Artifact.locked))
    locked_ids = {row[0] for row in artifact_rows.all() if row[1]}

    stale_ids = collect_dependent_artifacts(edges, changed_artifact_ids, locked_ids)
    if stale_ids:
        result = await session.execute(select(Artifact).where(Artifact.id.in_(stale_ids)))
        for artifact in result.scalars():
            artifact.status = ArtifactStatus.STALE
    return stale_ids
