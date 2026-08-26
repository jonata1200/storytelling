import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.config.provider_policy import effective_provider_for_channel, provider_model
from app.config.settings import get_settings
from app.core.enums import ArtifactStatus, ArtifactType, AssetKind, CostEntryType
from app.costs.models import CostEntry
from app.providers.image.types import (
    ImageGenerationRequest,
    ImageProvider,
)
from app.providers.image.types import (
    ImageReference as ProviderImageReference,
)
from app.providers.registry import resolve_image_provider
from app.providers.storage import generated_output_dir
from app.storage.service import apply_asset_storage_metadata
from app.visual_bible.artifacts import _add_dependency, _create_artifact
from app.visual_bible.models import Character, Location, VisualReference
from app.visual_bible.reference_queries import approved_visual_references

REFERENCE_STATUSES = {"generated", "approved", "rejected"}
IDENTITY_CHANGE_PATTERNS = (
    r"\b(?:trocar|mudar|alterar)\s+(?:a\s+)?idade\b",
    r"\b(?:trocar|mudar|alterar)\s+(?:o\s+)?cabelo\b",
    r"\b(?:rosto|face)\s+(?:diferente|novo|nova)\b",
)


def validate_identity_prompt(prompt: str, *, allow_identity_change: bool = False) -> None:
    if allow_identity_change:
        return
    normalized = str(prompt or "").casefold()
    if any(re.search(pattern, normalized) for pattern in IDENTITY_CHANGE_PATTERNS):
        raise ValueError(
            "O prompt contradiz características permanentes. Crie uma nova versão do "
            "perfil canônico para uma mudança deliberada de identidade."
        )


async def generate_visual_reference(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    view_type: str,
    *,
    prompt_override: str | None = None,
    provider: ImageProvider | None = None,
) -> VisualReference:
    target = await _visual_target(session, project_id, target_kind, target_id)
    if target is None:
        raise ValueError("Entidade visual não encontrada no projeto")
    profile, target_artifact_id, target_name = target
    canonical_prompt = str(profile.get("canonical_prompt") or "").strip()
    if not canonical_prompt:
        raise ValueError("Perfil canônico sem prompt visual")
    view_instruction = str(prompt_override or view_type).strip()
    validate_identity_prompt(view_instruction)
    prompt = (
        f"{canonical_prompt} Vista solicitada: {view_instruction}. Preserve rigorosamente "
        "identidade, idade, cabelo, traços marcantes, paleta e figurino canônicos. "
        "Sem texto e sem marca d'água."
    )

    settings = get_settings()
    provider_name = effective_provider_for_channel(settings, "image")
    image_provider = provider or resolve_image_provider(settings, provider_name)
    model = provider_model(settings, provider_name, "image")
    if not model:
        raise ValueError(f"Modelo de imagem não configurado para {provider_name}")
    prior_references = await approved_visual_references(
        session, project_id, target_kind, target_id
    )
    references = [
        ProviderImageReference(
            uri=asset.storage_uri,
            role="canonical" if reference.is_canonical else reference.view_type,
            metadata={"visual_reference_id": str(reference.id)},
        )
        for reference, asset in prior_references[:4]
    ]
    result = await image_provider.generate(
        ImageGenerationRequest(
            prompt=prompt,
            model=model,
            aspect_ratio="9:16",
            references=references,
            output_dir=generated_output_dir(
                "image", project_id, settings.local_storage_path
            ),
            metadata={
                "target_kind": target_kind,
                "target_id": str(target_id),
                "view_type": view_type,
            },
        )
    )
    artifact_payload = {
        "target_kind": target_kind,
        "target_id": str(target_id),
        "view_type": view_type,
        "prompt": prompt,
        "provider": result.provider,
        "model": result.model,
    }
    artifact = await _create_artifact(
        session,
        project_id,
        ArtifactType.VISUAL_REFERENCE,
        f"{target_name} — {view_type}",
        artifact_payload,
    )
    await _add_dependency(session, target_artifact_id, artifact.id)
    metadata = {
        "canonical": False,
        "reference_role": f"{target_kind}_{view_type}",
        "generation_seed": result.metadata.get("seed"),
        "external_generation_id": result.external_job_id,
        "provider_job_id": result.external_job_id,
        "source_mode": str(
            getattr(settings, f"{provider_name}_image_integration_mode", "api")
        ),
        "approved": False,
        "provider_metadata": result.metadata,
        "estimated_cost": result.estimated_cost,
        "vibes": {
            "ingredient_id": None,
            "ingredient_type": None,
            "synced_at": None,
            "sync_status": "not_synced",
        },
    }
    asset = Asset(
        project_id=project_id,
        artifact_id=artifact.id,
        kind=AssetKind.IMAGE,
        name=f"{target_name} — {view_type}",
        storage_uri=result.storage_uri,
        content_type=result.content_type,
        sha256=result.sha256,
        metadata_json=metadata,
    )
    apply_asset_storage_metadata(asset)
    session.add(asset)
    await session.flush()
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version_number=1,
            storage_uri=asset.storage_uri,
            sha256=asset.sha256,
            metadata_json=metadata,
        )
    )
    visual_reference = VisualReference(
        project_id=project_id,
        artifact_id=artifact.id,
        asset_id=asset.id,
        target_kind=target_kind,
        target_id=target_id,
        view_type=view_type,
        prompt=prompt,
        provider=result.provider,
        model=result.model,
        status="generated",
        is_canonical=False,
        metadata_json=metadata,
    )
    session.add(visual_reference)
    _record_cost(session, project_id, artifact.id, result)
    await session.commit()
    await session.refresh(visual_reference)
    return visual_reference


async def set_visual_reference_status(
    session: AsyncSession,
    project_id: UUID,
    reference_id: UUID,
    status: str,
    *,
    canonical: bool = False,
) -> VisualReference:
    normalized_status = str(status or "").strip().casefold()
    if normalized_status not in REFERENCE_STATUSES:
        raise ValueError("Status visual inválido")
    reference = await session.get(VisualReference, reference_id, with_for_update=True)
    if reference is None or reference.project_id != project_id:
        raise ValueError("Referência visual não encontrada")
    if canonical and normalized_status != "approved":
        raise ValueError("Somente referência aprovada pode ser canônica")
    if canonical:
        result = await session.execute(
            select(VisualReference).where(
                VisualReference.project_id == project_id,
                VisualReference.target_kind == reference.target_kind,
                VisualReference.target_id == reference.target_id,
                VisualReference.is_canonical.is_(True),
                VisualReference.id != reference.id,
            )
        )
        for previous in result.scalars():
            previous.is_canonical = False
            previous_metadata = dict(previous.metadata_json or {})
            previous_metadata["canonical"] = False
            previous.metadata_json = previous_metadata
        await session.flush()
    previous_status = reference.status
    previous_canonical = reference.is_canonical
    reference.status = normalized_status
    reference.is_canonical = canonical
    metadata = dict(reference.metadata_json or {})
    metadata["approved"] = normalized_status == "approved"
    metadata["canonical"] = canonical
    reference.metadata_json = metadata
    asset = await session.get(Asset, reference.asset_id, with_for_update=True)
    if asset is not None and (
        previous_status != normalized_status or previous_canonical != canonical
    ):
        asset_metadata = dict(asset.metadata_json or {})
        asset_metadata["approved"] = normalized_status == "approved"
        asset_metadata["canonical"] = canonical
        asset.current_version += 1
        asset.metadata_json = asset_metadata
        session.add(
            AssetVersion(
                asset_id=asset.id,
                version_number=asset.current_version,
                storage_uri=asset.storage_uri,
                sha256=asset.sha256,
                metadata_json=asset_metadata,
            )
        )
    artifact = await session.get(reference_artifact_type(), reference.artifact_id)
    if artifact is not None:
        artifact.status = (
            ArtifactStatus.APPROVED
            if normalized_status == "approved"
            else ArtifactStatus.REJECTED
            if normalized_status == "rejected"
            else ArtifactStatus.READY_FOR_REVIEW
        )
    await session.commit()
    await session.refresh(reference)
    return reference


def prepare_vibes_ingredient_metadata(
    reference: VisualReference,
    *,
    ingredient_id: str,
    ingredient_type: str,
) -> bool:
    if reference.status != "approved":
        raise ValueError("Somente referências aprovadas podem virar ingredients")
    metadata = dict(reference.metadata_json or {})
    vibes = dict(metadata.get("vibes") or {})
    if (
        vibes.get("ingredient_id") == ingredient_id
        and vibes.get("ingredient_type") == ingredient_type
        and vibes.get("sync_status") == "synced"
    ):
        return False
    vibes.update(
        {
            "ingredient_id": ingredient_id,
            "ingredient_type": ingredient_type,
            "synced_at": datetime.now(UTC).isoformat(),
            "sync_status": "synced",
        }
    )
    metadata["vibes"] = vibes
    reference.metadata_json = metadata
    return True


async def _visual_target(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
) -> tuple[dict, UUID, str] | None:
    target: Character | Location | None
    if target_kind == "character":
        target = await session.get(Character, target_id)
    elif target_kind == "location":
        target = await session.get(Location, target_id)
    else:
        return None
    if target is None or target.project_id != project_id:
        return None
    return dict(target.canonical_profile or {}), target.artifact_id, target.name


def reference_artifact_type() -> type[Any]:
    from app.projects.models import Artifact

    return Artifact


def _record_cost(
    session: AsyncSession,
    project_id: UUID,
    artifact_id: UUID,
    result: Any,
) -> None:
    try:
        total = Decimal(str(result.estimated_cost or "0"))
    except InvalidOperation:
        total = Decimal("0")
    session.add(
        CostEntry(
            project_id=project_id,
            artifact_id=artifact_id,
            entry_type=CostEntryType.ACTUAL,
            provider=result.provider,
            model=result.model,
            operation="image_generation",
            quantity=Decimal("1"),
            unit="image",
            unit_cost=total,
            total_cost=total,
            metadata_json={"external_generation_id": result.external_job_id},
        )
    )
