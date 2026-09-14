import re
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.config.provider_policy import effective_provider_for_channel, provider_model
from app.config.settings import get_settings
from app.core.enums import (
    MEDIA_MAX_ATTEMPTS,
    ArtifactStatus,
    ArtifactType,
    AssetKind,
    CostEntryType,
    GenerationJobType,
)
from app.costs.models import CostEntry
from app.jobs.service import JobEnqueueDecision, create_or_get_media_job, dispatch_media_job
from app.providers.image.meta_browser import meta_image_browser_backend_available
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
from app.visual_bible.prompt_balance import repair_portuguese_mojibake
from app.visual_bible.reference_queries import approved_visual_references

REFERENCE_STATUSES = {"generated", "approved", "rejected"}
IDENTITY_CHANGE_PATTERNS = (
    r"\b(?:trocar|mudar|alterar)\s+(?:a\s+)?idade\b",
    r"\b(?:trocar|mudar|alterar)\s+(?:o\s+)?cabelo\b",
    r"\b(?:rosto|face)\s+(?:diferente|novo|nova)\b",
)

# A Meta AI recusa prompts com armas/ferimentos explícitos (ex.: "marca de faca")
# e responde com texto em vez de imagem. Reescrevemos os gatilhos conhecidos por
# equivalentes canônicos neutros apenas na camada técnica do provedor; o texto
# salvo no perfil canônico e na referência permanece intacto. Gatilhos sem
# equivalente canônico (ex.: gore ativo) ficam a cargo da detecção de recusa do
# bridge, que falha rápido e reporta o motivo ao usuário.
META_IMAGE_PROMPT_REWRITES: tuple[tuple[str, str], ...] = (
    (r"marcas? de facadas?", "cicatriz de faca"),
    (r"marcas? de faca", "cicatriz de faca"),
    (r"cicatrizes? de facadas?", "cicatriz de faca"),
    (r"feridas? abertas?", "cicatriz"),
    (r"cortes? fundos?", "cicatriz"),
    (r"cortes? profundos?", "cicatriz"),
    (r"ensanguentad(o|a|os|as)", r"machucad\1"),
    (r"(?<!sem )\bsangue\b", "hematomas"),
)


def sanitize_meta_image_prompt(prompt: str) -> str:
    """Remove gatilhos conhecidos de recusa da Meta sem alterar o texto salvo."""
    sanitized = str(prompt or "")
    for pattern, replacement in META_IMAGE_PROMPT_REWRITES:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    return re.sub(r"[ \t]{2,}", " ", sanitized).strip()


def _strip_view_instructions(prompt: str, target_kind: str) -> str:
    """Separa o prompt canônico "base" do prompt final (INC-08).

    O prompt salvo na referência carrega as instruções técnicas da vista
    (CHARACTER_META_INSTRUCTION / instruções de establishing) embutidas. Para
    que uma regeneração nunca copie o prompt final acumulado como base, a
    edição do usuário é gravada no metadata SEM essas instruções; o texto
    técnico é sempre reconstruído na camada do provedor.
    """
    from app.visual_bible.reference_planning import (
        CHARACTER_META_INSTRUCTION,
        LOCATION_BASE_VIEWS,
    )

    text = str(prompt or "").strip()
    if target_kind == "character" and text.endswith(CHARACTER_META_INSTRUCTION):
        return text[: -len(CHARACTER_META_INSTRUCTION)].strip()
    if target_kind == "location":
        for _view, instruction, _priority in LOCATION_BASE_VIEWS:
            if instruction and text.endswith(instruction):
                return text[: -len(instruction)].strip()
    return text


def visual_reference_aspect_ratio(target_kind: str) -> str:
    _ = target_kind
    return "9:16"


async def enqueue_visual_reference_generation(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    view_type: str,
    *,
    prompt_override: str | None = None,
    attempt_key: str = "initial",
) -> JobEnqueueDecision:
    settings = get_settings()
    unavailable_reason = visual_reference_generation_issue(settings)
    if unavailable_reason:
        raise RuntimeError(unavailable_reason)
    decision = await create_or_get_media_job(
        session,
        project_id,
        job_type=GenerationJobType.IMAGE,
        operation="generate_visual_reference",
        payload={
            "target_kind": target_kind,
            "target_id": str(target_id),
            "view_type": view_type,
            "prompt_override": prompt_override,
        },
        provider="meta",
        model=settings.meta_image_model,
        attempt_key=attempt_key,
        max_attempts=MEDIA_MAX_ATTEMPTS,
    )
    if decision.should_dispatch:
        await dispatch_media_job(decision.job)
    return decision


def validate_identity_prompt(prompt: str, *, allow_identity_change: bool = False) -> None:
    if allow_identity_change:
        return
    normalized = str(prompt or "").casefold()
    if any(re.search(pattern, normalized) for pattern in IDENTITY_CHANGE_PATTERNS):
        raise ValueError(
            "O prompt contradiz características permanentes. Crie uma nova versão do "
            "perfil canônico para uma mudança deliberada de identidade."
        )


def visual_reference_generation_issue(
    settings: Any | None = None,
    *,
    browser_backend_available: bool | None = None,
) -> str:
    """Return the actionable reason image generation is unavailable, if any."""
    current_settings = settings or get_settings()
    provider_name = effective_provider_for_channel(current_settings, "image")
    model = provider_model(current_settings, provider_name, "image")
    if not model:
        return f"Configure o modelo de imagem do provedor {provider_name}."
    if provider_name == "meta" and not current_settings.meta_browser_automation_enabled:
        return (
            "A geração de imagens está desativada. Instale e autorize o backend de browser "
            "do Meta Image e habilite a automação de imagens nos Ajustes."
        )
    backend_ready = (
        meta_image_browser_backend_available()
        if browser_backend_available is None
        else browser_backend_available
    )
    if provider_name == "meta" and not backend_ready:
        return (
            "A automação está habilitada, mas nenhum backend autorizado do Meta Image está "
            "instalado. Instale um plugin no grupo storytelling.meta_image_browser."
        )
    return ""


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
    canonical_prompt = repair_portuguese_mojibake(profile.get("canonical_prompt")).strip()
    if not canonical_prompt:
        raise ValueError("Perfil canônico sem prompt visual")
    custom_prompt = repair_portuguese_mojibake(prompt_override).strip()
    if custom_prompt:
        validate_identity_prompt(custom_prompt)
        prompt = custom_prompt
    else:
        prompt = (
            f"{canonical_prompt} Vista solicitada: {view_type}. Preserve rigorosamente "
            "identidade, idade, cabelo, traços marcantes, paleta e figurino canônicos. "
            "Sem texto e sem marca d'água."
        )
    # Prompt canônico base separado do final (INC-08): regenerações derivam o
    # override da base (sem instruções técnicas acumuladas), nunca do final.
    base_prompt = _strip_view_instructions(prompt, target_kind)

    settings = get_settings()
    provider_name = effective_provider_for_channel(settings, "image")
    image_provider = provider or resolve_image_provider(settings, provider_name)
    model = provider_model(settings, provider_name, "image")
    if not model:
        raise ValueError(f"Modelo de imagem não configurado para {provider_name}")
    prior_references = await approved_visual_references(session, project_id, target_kind, target_id)
    references = [
        ProviderImageReference(
            uri=asset.storage_uri,
            role="canonical" if reference.is_canonical else reference.view_type,
            metadata={"visual_reference_id": str(reference.id)},
        )
        for reference, asset in prior_references[:4]
    ]
    provider_prompt = _visual_reference_provider_prompt(prompt, target_kind, view_type)
    result = await image_provider.generate(
        ImageGenerationRequest(
            prompt=provider_prompt,
            model=model,
            aspect_ratio=visual_reference_aspect_ratio(target_kind),
            references=references,
            output_dir=generated_output_dir("image", project_id, settings.local_storage_path),
            metadata={
                "project_id": str(project_id),
                "target_kind": target_kind,
                "target_id": str(target_id),
                "view_type": view_type,
            },
        )
    )
    previous_result = await session.execute(
        select(VisualReference).where(
            VisualReference.project_id == project_id,
            VisualReference.target_kind == target_kind,
            VisualReference.target_id == target_id,
            VisualReference.status != "rejected",
        )
    )
    for previous in previous_result.scalars():
        if target_kind == "character" or previous.view_type == view_type:
            previous.status = "rejected"
            previous.is_canonical = False
            previous.metadata_json = {
                **dict(previous.metadata_json or {}),
                "approved": False,
                "canonical": False,
                "superseded": True,
            }
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
    artifact.status = ArtifactStatus.APPROVED
    await _add_dependency(session, target_artifact_id, artifact.id)
    metadata = {
        "canonical": True,
        "reference_role": f"{target_kind}_{view_type}",
        "generation_seed": result.metadata.get("seed"),
        "external_generation_id": result.external_job_id,
        "provider_job_id": result.external_job_id,
        "source_mode": str(getattr(settings, f"{provider_name}_image_integration_mode", "api")),
        "approved": True,
        "provider_metadata": result.metadata,
        "estimated_cost": result.estimated_cost,
        # Prompt canônico base (sem instruções técnicas de vista) para que a
        # UI derive regenerações da base, não do prompt final acumulado.
        "canonical_base_prompt": base_prompt,
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
        status="approved",
        is_canonical=True,
        metadata_json=metadata,
    )
    session.add(visual_reference)
    _record_cost(session, project_id, artifact.id, result)
    await session.commit()
    await session.refresh(visual_reference)
    return visual_reference


def _visual_reference_provider_prompt(prompt: str, target_kind: str, view_type: str) -> str:
    """Mantém as regras técnicas fora do campo editável pelo usuário."""
    if target_kind == "character":
        from app.visual_bible.reference_planning import CHARACTER_META_INSTRUCTION

        clean_prompt = sanitize_meta_image_prompt(prompt.strip())
        if CHARACTER_META_INSTRUCTION in clean_prompt:
            return clean_prompt
        return f"{clean_prompt} {CHARACTER_META_INSTRUCTION}".strip()
    if target_kind == "location":
        technical = (
            "Preserve a geografia, arquitetura, materiais, paleta e iluminação do ambiente. "
            "Não inclua pessoas, texto, marcas d'água, fundo neutro ou aparência de estúdio."
        )
    else:
        technical = "Não inclua texto ou marca d'água."
    return f"{sanitize_meta_image_prompt(prompt.strip())}\n\n{technical}".strip()


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


# prepare_vibes_ingredient_metadata was removed because Vibes has been deleted


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
