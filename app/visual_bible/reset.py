from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.costs.models import CostEntry
from app.generation.models import PromptExecution
from app.projects.models import Approval, Artifact, ArtifactVersion
from app.storage.service import resolve_storage_path
from app.video_generation.models import VideoClip
from app.visual_bible.models import Character, Location, VisualReference
from app.workflows.models import ArtifactDependency

VISUAL_RESET_BLOCKER_MODELS = (("video_clips", VideoClip),)


def _delete_local_storage_file(storage_uri: str) -> bool:
    """Delete a local storage file if it exists."""
    if not storage_uri or storage_uri.startswith(("http://", "https://", "data:")):
        return False
    path = resolve_storage_path(storage_uri)
    if path is None:
        return False
    try:
        if path.exists():
            path.unlink()
            return True
    except OSError:
        pass
    return False


async def visual_bible_reset_blockers(
    session: AsyncSession,
    project_id: UUID,
) -> dict[str, int]:
    blockers: dict[str, int] = {}
    for key, model in VISUAL_RESET_BLOCKER_MODELS:
        result = await session.execute(select(model.id).where(model.project_id == project_id))
        count = len(result.all())
        if count:
            blockers[key] = count
    return blockers


def visual_bible_reset_blocker_message(blockers: dict[str, int]) -> str:
    labels = {
        "video_clips": "clipes de video",
    }
    details = ", ".join(
        f"{labels.get(key, key)}: {value}" for key, value in sorted(blockers.items())
    )
    return (
        "Não posso apagar e recriar a Biblioteca Visual porque o projeto já avançou "
        f"além da etapa de personagens ({details})."
    )


async def reset_visual_bible(
    session: AsyncSession,
    project_id: UUID,
) -> dict[str, int]:
    blockers = await visual_bible_reset_blockers(session, project_id)
    if blockers:
        raise ValueError(visual_bible_reset_blocker_message(blockers))

    character_result = await session.execute(
        select(Character.id, Character.artifact_id).where(Character.project_id == project_id)
    )
    location_result = await session.execute(
        select(Location.id, Location.artifact_id).where(Location.project_id == project_id)
    )
    reference_result = await session.execute(
        select(VisualReference.id, VisualReference.artifact_id, VisualReference.asset_id).where(
            VisualReference.project_id == project_id
        )
    )

    character_rows = character_result.all()
    location_rows = location_result.all()
    reference_rows = reference_result.all()

    character_ids = [row[0] for row in character_rows]
    location_ids = [row[0] for row in location_rows]
    reference_ids = [row[0] for row in reference_rows]
    asset_ids = {row[2] for row in reference_rows if row[2] is not None}
    artifact_ids = {
        row[1]
        for rows in (character_rows, location_rows, reference_rows)
        for row in rows
        if row[1] is not None
    }

    asset_storage_uris: list[str] = []
    if asset_ids:
        storage_result = await session.execute(
            select(Asset.storage_uri).where(
                Asset.project_id == project_id,
                Asset.id.in_(asset_ids),
            )
        )
        asset_storage_uris = [str(row[0] or "") for row in storage_result.all()]

    if reference_ids:
        await session.execute(delete(VisualReference).where(VisualReference.id.in_(reference_ids)))
    if character_ids:
        await session.execute(delete(Character).where(Character.id.in_(character_ids)))
    if location_ids:
        await session.execute(delete(Location).where(Location.id.in_(location_ids)))
    if asset_ids:
        await session.execute(delete(AssetVersion).where(AssetVersion.asset_id.in_(asset_ids)))
        await session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    if artifact_ids:
        await session.execute(
            delete(CostEntry).where(
                CostEntry.project_id == project_id,
                CostEntry.artifact_id.in_(artifact_ids),
            )
        )
        await session.execute(
            delete(PromptExecution).where(
                PromptExecution.project_id == project_id,
                PromptExecution.artifact_id.in_(artifact_ids),
            )
        )
        await session.execute(
            delete(ArtifactDependency).where(
                (ArtifactDependency.upstream_artifact_id.in_(artifact_ids))
                | (ArtifactDependency.downstream_artifact_id.in_(artifact_ids))
            )
        )
        await session.execute(delete(Approval).where(Approval.artifact_id.in_(artifact_ids)))
        await session.execute(
            delete(ArtifactVersion).where(ArtifactVersion.artifact_id.in_(artifact_ids))
        )
        await session.execute(delete(Artifact).where(Artifact.id.in_(artifact_ids)))

    await session.flush()
    await session.commit()
    # Delete files AFTER commit so DB rows are persisted. If commit fails,
    # files are preserved (DB rows remain, consistent state).
    deleted_files = sum(
        1 for storage_uri in asset_storage_uris if _delete_local_storage_file(storage_uri)
    )
    return {
        "characters": len(character_ids),
        "locations": len(location_ids),
        "visual_references": len(reference_ids),
        "assets": len(asset_ids),
        "artifacts": len(artifact_ids),
        "files": deleted_files,
    }


async def delete_visual_target(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
) -> bool:
    """Delete a single character or location and its associated visual assets/artifacts."""
    character_ids: list[UUID] = []
    location_ids: list[UUID] = []
    target_artifact_id: UUID | None = None

    if target_kind == "character":
        char = await session.get(Character, target_id)
        if char is None or char.project_id != project_id:
            return False
        character_ids = [target_id]
        target_artifact_id = char.artifact_id
    elif target_kind == "location":
        loc = await session.get(Location, target_id)
        if loc is None or loc.project_id != project_id:
            return False
        location_ids = [target_id]
        target_artifact_id = loc.artifact_id
    else:
        return False

    reference_result = await session.execute(
        select(VisualReference.id, VisualReference.artifact_id, VisualReference.asset_id).where(
            VisualReference.project_id == project_id,
            VisualReference.target_kind == target_kind,
            VisualReference.target_id == target_id,
        )
    )
    reference_rows = reference_result.all()
    reference_ids = [row[0] for row in reference_rows]
    asset_ids = {row[2] for row in reference_rows if row[2] is not None}
    artifact_ids = {
        artifact_id
        for artifact_id in [target_artifact_id, *(row[1] for row in reference_rows)]
        if artifact_id is not None
    }

    asset_storage_uris: list[str] = []
    if asset_ids:
        storage_result = await session.execute(
            select(Asset.storage_uri).where(
                Asset.project_id == project_id,
                Asset.id.in_(asset_ids),
            )
        )
        asset_storage_uris = [str(row[0] or "") for row in storage_result.all()]

    if reference_ids:
        await session.execute(delete(VisualReference).where(VisualReference.id.in_(reference_ids)))
    if character_ids:
        await session.execute(delete(Character).where(Character.id.in_(character_ids)))
    if location_ids:
        await session.execute(delete(Location).where(Location.id.in_(location_ids)))
    if asset_ids:
        await session.execute(delete(AssetVersion).where(AssetVersion.asset_id.in_(asset_ids)))
        await session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    if artifact_ids:
        await session.execute(
            delete(CostEntry).where(
                CostEntry.project_id == project_id,
                CostEntry.artifact_id.in_(artifact_ids),
            )
        )
        await session.execute(
            delete(PromptExecution).where(
                PromptExecution.project_id == project_id,
                PromptExecution.artifact_id.in_(artifact_ids),
            )
        )
        await session.execute(
            delete(ArtifactDependency).where(
                (ArtifactDependency.upstream_artifact_id.in_(artifact_ids))
                | (ArtifactDependency.downstream_artifact_id.in_(artifact_ids))
            )
        )
        await session.execute(delete(Approval).where(Approval.artifact_id.in_(artifact_ids)))
        await session.execute(
            delete(ArtifactVersion).where(ArtifactVersion.artifact_id.in_(artifact_ids))
        )
        await session.execute(delete(Artifact).where(Artifact.id.in_(artifact_ids)))

    await session.flush()
    await session.commit()
    for storage_uri in asset_storage_uris:
        _delete_local_storage_file(storage_uri)
    return True
