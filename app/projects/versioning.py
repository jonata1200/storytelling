from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus
from app.projects.models import Artifact, ArtifactVersion
from app.workflows.dependencies import collect_dependent_artifacts
from app.workflows.models import ArtifactDependency

INACTIVE_DERIVED_STATUSES = {ArtifactStatus.STALE, ArtifactStatus.CANCELLED}


async def create_artifact_version(
    session: AsyncSession,
    artifact: Artifact,
    payload: dict,
    change_note: str | None = None,
    mark_downstream_stale: bool = True,
) -> ArtifactVersion:
    locked_artifact = await session.get(Artifact, artifact.id, with_for_update=True)
    if locked_artifact is None:
        raise ValueError("Artifact not found")
    artifact = locked_artifact
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
    if mark_downstream_stale:
        await mark_dependents_stale(session, {artifact.id})
    return version


async def mark_dependents_stale(
    session: AsyncSession, changed_artifact_ids: set[UUID]
) -> set[UUID]:
    changed_rows = await session.execute(
        select(Artifact.id, Artifact.project_id).where(Artifact.id.in_(changed_artifact_ids))
    )
    changed_projects = {row[1] for row in changed_rows.all()}
    if len(changed_projects) != 1:
        raise ValueError("Changed artifacts must belong to exactly one project")
    project_id = next(iter(changed_projects))

    dependency_rows = await session.execute(
        select(
            ArtifactDependency.upstream_artifact_id,
            ArtifactDependency.downstream_artifact_id,
        )
        .join(Artifact, Artifact.id == ArtifactDependency.upstream_artifact_id)
        .where(Artifact.project_id == project_id)
    )
    edges = [(row[0], row[1]) for row in dependency_rows.all()]

    artifact_rows = await session.execute(
        select(Artifact.id, Artifact.locked).where(Artifact.project_id == project_id)
    )
    locked_ids = {row[0] for row in artifact_rows.all() if row[1]}

    stale_ids = collect_dependent_artifacts(edges, changed_artifact_ids, locked_ids)
    if stale_ids:
        result = await session.execute(select(Artifact).where(Artifact.id.in_(stale_ids)))
        for artifact in result.scalars():
            artifact.status = ArtifactStatus.STALE
    return stale_ids


async def resolve_stale_artifacts_after_regeneration(
    session: AsyncSession,
    project_id: UUID,
) -> int:
    result = await session.execute(
        select(Artifact).where(
            Artifact.project_id == project_id,
            Artifact.status == ArtifactStatus.STALE,
        )
    )
    resolved_count = 0
    for artifact in result.scalars():
        artifact.status = ArtifactStatus.CANCELLED
        resolved_count += 1
    if resolved_count:
        await session.flush()
        await session.commit()
    return resolved_count
