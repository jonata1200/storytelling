"""Helpers de exclusão manual de perfis (cards) da Bíblia Visual.

Separado de `manual_references` para manter a checagem de jobs ativos longe
do ciclo de imports do service da Bíblia Visual.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.core.enums import ArtifactStatus, AssetKind, GenerationJobStatus, GenerationJobType
from app.projects.models import Artifact
from app.visual_bible.models import VisualReference

ACTIVE_JOB_STATUSES = {
    GenerationJobStatus.PENDING,
    GenerationJobStatus.RUNNING,
    GenerationJobStatus.RETRY_SCHEDULED,
}


async def active_reference_jobs_exist(
    session: AsyncSession, project_id: UUID, target_id: UUID
) -> bool:
    """True se há job de imagem ATIVO enfileirado para o alvo deste card."""
    from app.video_generation.models import GenerationJob

    result = await session.execute(
        select(GenerationJob.id).where(
            GenerationJob.project_id == project_id,
            GenerationJob.job_type == GenerationJobType.IMAGE,
            GenerationJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    for (payload,) in result.all():
        request_payload = dict(payload or {})
        if str(request_payload.get("target_id") or "") == str(target_id):
            return True
    return False


async def delete_profile_references(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
) -> list[str]:
    """Rejeita todas as referências do alvo e retorna os arquivos a apagar.

    Marca VisualReference como rejected, rejeita os artifacts/assets filhos e
    devolve os `storage_uri` para exclusão APÓS o commit do chamador (mesma
    semântica de `delete_visual_reference`).
    """

    result = await session.execute(
        select(VisualReference).where(
            VisualReference.project_id == project_id,
            VisualReference.target_kind == target_kind,
            VisualReference.target_id == target_id,
        )
    )
    references = list(result.scalars())
    storage_uris: list[str] = []
    for reference in references:
        reference.status = "rejected"
        reference.is_canonical = False
        reference.metadata_json = {
            **dict(reference.metadata_json or {}),
            "approved": False,
            "canonical": False,
            "deleted_at": datetime.now(UTC).isoformat(),
        }
        artifact = await session.get(Artifact, reference.artifact_id)
        if artifact is not None:
            artifact.status = ArtifactStatus.REJECTED
        asset: Asset | None = (
            await session.get(Asset, reference.asset_id)
            if reference.asset_id is not None
            else None
        )
        if asset is not None:
            uri = str(asset.storage_uri or "")
            asset_metadata = dict(asset.metadata_json or {})
            asset_metadata["approved"] = False
            asset_metadata["canonical"] = False
            asset.metadata_json = asset_metadata
            if uri:
                storage_uris.append(uri)
    return storage_uris


def _unused(*_args: Any) -> None:
    # AssetKind importado para documentar a dependência; referências de perfil
    # são sempre imagens, mas a exclusão não filtra por kind.
    _ = AssetKind.IMAGE


__all__ = [
    "active_reference_jobs_exist",
    "delete_profile_references",
]