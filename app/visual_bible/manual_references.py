"""Referências visuais manuais na Bíblia Visual.

Permite ao usuário enviar uma imagem manualmente para um personagem/local e
remover referências consideradas desnecessárias. A imagem enviada substitui a
referência canônica atual do alvo (mesma semântica do fluxo gerado:
`generate_visual_reference` rejeita as anteriores).
"""

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.core.enums import ArtifactStatus, ArtifactType, AssetKind
from app.production.models import ProjectProductionSettings
from app.projects.models import Artifact
from app.providers.storage import generated_output_dir
from app.storage.service import (
    apply_asset_storage_metadata,
    delete_local_storage_files,
)
from app.visual_bible.artifacts import _add_dependency, _create_artifact
from app.visual_bible.models import Character, Location, VisualReference

ALLOWED_MANUAL_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

MANUAL_UPLOAD_MAX_BYTES = 20 * 1024 * 1024  # 20 MB é folga; imagens reais ficam << disso.


class ManualReferenceError(ValueError):
    """Erro de validação do upload manual, com mensagem para o usuário."""


def _validate_manual_image(content_type: str, size_bytes: int) -> None:
    normalized = str(content_type or "").split(";")[0].strip().lower()
    if normalized not in ALLOWED_MANUAL_IMAGE_TYPES:
        raise ManualReferenceError(
            "Formato de imagem não suportado. Envie PNG, JPG ou WEBP."
        )
    if size_bytes <= 0:
        raise ManualReferenceError("O arquivo enviado está vazio.")
    if size_bytes > MANUAL_UPLOAD_MAX_BYTES:
        raise ManualReferenceError("A imagem excede o limite de 20 MB.")


def _visual_target_name(target: Any) -> str:
    return str(getattr(target, "name", "") or "Referência")


async def save_manual_visual_reference(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    view_type: str,
    *,
    filename: str,
    content_type: str,
    data: bytes,
    target: Any = None,
    source_artifact_id: UUID | None = None,
) -> VisualReference:
    """Persiste uma imagem enviada manualmente como referência visual canônica.

    Rejeita as referências anteriores do mesmo alvo (mesma semântica do fluxo
    gerado), registra o artifact, o asset e o custo zero.
    """
    _validate_manual_image(content_type, len(data))
    display_name = _visual_target_name(target)
    view_label = str(view_type or "manual").strip() or "manual"

    artifact_payload = {
        "target_kind": target_kind,
        "target_id": str(target_id),
        "view_type": view_label,
        "prompt": f"Imagem enviada manualmente pelo usuário ({filename}).",
        "provider": "manual",
        "model": "manual_upload",
    }
    artifact = await _create_artifact(
        session,
        project_id,
        ArtifactType.VISUAL_REFERENCE,
        f"{display_name} — {view_label}",
        artifact_payload,
    )
    artifact.status = ArtifactStatus.APPROVED
    if source_artifact_id is not None:
        await _add_dependency(session, source_artifact_id, artifact.id)

    metadata = {
        "canonical": True,
        "reference_role": f"{target_kind}_{view_label}",
        "source_mode": "manual_upload",
        "approved": True,
        "uploaded_at": datetime.now(UTC).isoformat(),
        "uploaded_filename": str(filename or ""),
        "estimated_cost": "0.000000",
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
        name=f"{display_name} — {view_label} (manual)",
        storage_uri="",  # preenchido logo abaixo após gravar o arquivo
        content_type=content_type.split(";")[0],
        sha256=hashlib.sha256(data).hexdigest(),
        metadata_json=metadata,
    )
    output_dir = generated_output_dir("image", project_id, None)
    output_dir.mkdir(parents=True, exist_ok=True)
    extension = ALLOWED_MANUAL_IMAGE_TYPES[content_type.split(";")[0].lower()]
    destination = output_dir / f"manual-{artifact.id}{extension}"
    destination.write_bytes(data)
    asset.storage_uri = destination.as_posix()
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

    previous_result = await session.execute(
        select(VisualReference).where(
            VisualReference.project_id == project_id,
            VisualReference.target_kind == target_kind,
            VisualReference.target_id == target_id,
            VisualReference.status != "rejected",
        )
    )
    for previous in previous_result.scalars():
        previous.status = "rejected"
        previous.is_canonical = False
        previous.metadata_json = {
            **dict(previous.metadata_json or {}),
            "approved": False,
            "canonical": False,
            "superseded": True,
        }

    visual_reference = VisualReference(
        project_id=project_id,
        artifact_id=artifact.id,
        asset_id=asset.id,
        target_kind=target_kind,
        target_id=target_id,
        view_type=view_label,
        prompt=artifact_payload["prompt"],
        provider="manual",
        model="manual_upload",
        status="approved",
        is_canonical=True,
        metadata_json=metadata,
    )
    session.add(visual_reference)
    await session.commit()
    await session.refresh(visual_reference)
    return visual_reference


async def delete_visual_reference(
    session: AsyncSession,
    project_id: UUID,
    reference_id: UUID,
) -> bool:
    """Remove uma referência visual: marca rejected, desvincula o asset e
    remove o arquivo do storage. Retorna True se a referência existia."""
    reference = await session.get(VisualReference, reference_id)
    if reference is None or reference.project_id != project_id:
        return False
    reference.status = "rejected"
    reference.is_canonical = False
    metadata = dict(reference.metadata_json or {})
    metadata["approved"] = False
    metadata["canonical"] = False
    metadata["deleted_at"] = datetime.now(UTC).isoformat()
    reference.metadata_json = metadata

    artifact = await session.get(Artifact, reference.artifact_id)
    if artifact is not None:
        artifact.status = ArtifactStatus.REJECTED
    asset = await session.get(Asset, reference.asset_id)
    storage_uri = ""
    if asset is not None:
        storage_uri = str(asset.storage_uri or "")
        asset_metadata = dict(asset.metadata_json or {})
        asset_metadata["approved"] = False
        asset_metadata["canonical"] = False
        asset.metadata_json = asset_metadata
    await session.commit()
    if storage_uri:
        delete_local_storage_files([storage_uri])
    return True


# ---------------------------------------------------------------------------
# Exclusão manual de perfis (cards) da Bíblia Visual
# ---------------------------------------------------------------------------
VISUAL_EXCLUSIONS_KEY = "visual_exclusions"


def visual_exclusion_keys(target_kind: str, name: str, permanent_id: str = "") -> set[str]:
    """Todas as variantes de chave do alvo, normalizadas com `_visual_key`.

    O tombstone grava as MESMAS chaves derivadas aqui. O `permanent_id` dos
    perfis é o sha1 determinístico do nome (`char_…`/`loc_…`), e o fallback
    por nome normalizado cobre variações de caixa/acentuação entre extrações
    — as duas formas casam em ambos os lados (gravação e filtro).
    """
    from app.visual_bible.profiles import _visual_key

    keys: set[str] = set()
    normalized_id = _visual_key(permanent_id)
    if normalized_id:
        keys.add(f"{target_kind}:{normalized_id}")
    normalized_name = _visual_key(name)
    if normalized_name:
        keys.add(f"{target_kind}:{normalized_name}")
    return keys


def visual_exclusion_key(target_kind: str, target: Any) -> str:
    """Chave primária do alvo (primeira variante de `visual_exclusion_keys`)."""
    profile = dict(getattr(target, "canonical_profile", None) or {})
    permanent_id = str(profile.get("permanent_id") or "").strip()
    name = str(getattr(target, "name", "") or "").strip()
    keys = visual_exclusion_keys(target_kind, name, permanent_id)
    return next(iter(sorted(keys)), f"{target_kind}:{_visual_key_fallback(name)}")


def _visual_key_fallback(name: str) -> str:
    from app.visual_bible.profiles import _visual_key

    return _visual_key(name)


def visual_exclusion_label(target_kind: str, target: Any) -> str:
    kind_label = "Personagem" if target_kind == "character" else "Local"
    return f"{kind_label}: {getattr(target, 'name', '')}"


async def _production_settings_row(
    session: AsyncSession, project_id: UUID
) -> ProjectProductionSettings | None:
    return (
        await session.execute(
            select(ProjectProductionSettings).where(
                ProjectProductionSettings.project_id == project_id
            )
        )
    ).scalars().first()


async def load_visual_exclusions(
    session: AsyncSession, project_id: UUID
) -> list[dict[str, Any]]:
    """Exclusões manuais persistidas nas production settings do projeto."""
    settings = await _production_settings_row(session, project_id)
    entries = dict(settings.metadata_json or {}).get(VISUAL_EXCLUSIONS_KEY) if settings else None
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("key")]


async def add_visual_exclusion(
    session: AsyncSession,
    project_id: UUID,
    *,
    key: str,
    label: str,
    alt_keys: set[str] | None = None,
) -> None:
    """Grava o tombstone que impede o retorno do perfil em regenerações."""
    settings = await _production_settings_row(session, project_id)
    if settings is None:
        settings = ProjectProductionSettings(project_id=project_id)
        session.add(settings)
        await session.flush()
    metadata = dict(settings.metadata_json or {})
    entries: list[dict[str, Any]] = [
        e for e in metadata.get(VISUAL_EXCLUSIONS_KEY) or [] if isinstance(e, dict)
    ]
    existing_by_key = {str(e.get("key") or ""): e for e in entries}
    if key not in existing_by_key:
        entry: dict[str, Any] = {
            "key": key,
            "label": label,
            "excluded_at": datetime.now(UTC).isoformat(),
        }
        if alt_keys:
            entry["alt_keys"] = sorted(k for k in alt_keys if k != key)
        entries.append(entry)
    elif alt_keys:
        merged_alts = sorted(
            (set(existing_by_key[key].get("alt_keys") or []) | set(alt_keys)) - {key}
        )
        existing_by_key[key]["alt_keys"] = merged_alts
    metadata[VISUAL_EXCLUSIONS_KEY] = entries
    settings.metadata_json = metadata
    await session.commit()


async def remove_visual_exclusion(session: AsyncSession, project_id: UUID, key: str) -> bool:
    """Remove um tombstone; o card volta na próxima geração da Bíblia Visual."""
    settings = await _production_settings_row(session, project_id)
    if settings is None:
        return False
    metadata = dict(settings.metadata_json or {})
    entries: list[dict[str, Any]] = [
        e for e in metadata.get(VISUAL_EXCLUSIONS_KEY) or [] if isinstance(e, dict)
    ]
    removed_keys: set[str] = set()
    for entry in entries:
        entry_keys = {str(entry.get("key") or "")}
        entry_keys.update(str(alt) for alt in entry.get("alt_keys") or [])
        if key in entry_keys:
            removed_keys |= entry_keys
    if not removed_keys:
        return False
    remaining = [
        e
        for e in entries
        if not removed_keys.intersection(
            {str(e.get("key") or ""), *(str(alt) for alt in e.get("alt_keys") or [])}
        )
    ]
    if len(remaining) == len(entries):
        return False
    metadata[VISUAL_EXCLUSIONS_KEY] = remaining
    settings.metadata_json = metadata
    await session.commit()
    return True


async def delete_visual_profile(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
) -> bool:
    """Exclui manualmente um card (perfil) da Bíblia Visual.

    Remove Character/Location + Artifact com a ordem FK-safe (edges nas duas
    pontas → approvals → artifact_versions → referências + assets + arquivos →
    linha do perfil → artifact) e grava um tombstone nas production settings
    para que a próxima geração da Bíblia Visual NÃO recrie o perfil a partir
    do roteiro. Retorna False se o alvo não existir no projeto.
    """
    from sqlalchemy import delete as sa_delete

    from app.projects.models import Approval, ArtifactVersion
    from app.visual_bible.profile_exclusion import (
        active_reference_jobs_exist,
        delete_profile_references,
    )
    from app.workflows.models import ArtifactDependency

    if target_kind not in {"character", "location"}:
        raise ValueError("Tipo de alvo inválido para exclusão de perfil visual")
    model: Any = Character if target_kind == "character" else Location
    target = await session.get(model, target_id)
    if target is None or target.project_id != project_id:
        return False
    if await active_reference_jobs_exist(session, project_id, target_id):
        raise RuntimeError(
            "Há uma geração de referência em andamento para este card. "
            "Aguarde concluir ou cancele o job antes de excluir."
        )

    artifact_id = target.artifact_id
    profile = dict(target.canonical_profile or {})
    keys = visual_exclusion_keys(
        target_kind, str(target.name or ""), str(profile.get("permanent_id") or "")
    )
    key = next(iter(sorted(keys)), "")
    label = visual_exclusion_label(target_kind, target)

    # Referências do alvo: marca rejected, desvincula assets e coleta os
    # arquivos para apagar APÓS o commit (mesma ordem de delete_visual_reference).
    storage_uris = await delete_profile_references(
        session, project_id, target_kind, target_id
    )

    # 1) Edges de dependência nas DUAS pontas (o artifact pode ser upstream de
    #    referências visuais e downstream do script).
    await session.execute(
        sa_delete(ArtifactDependency).where(
            or_(
                ArtifactDependency.upstream_artifact_id == artifact_id,
                ArtifactDependency.downstream_artifact_id == artifact_id,
            )
        )
    )
    # 2) Approvals e versions (FK sem cascade; o cascade do ORM não dispara
    #    para statements de Core).
    await session.execute(sa_delete(Approval).where(Approval.artifact_id == artifact_id))
    await session.execute(
        sa_delete(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact_id)
    )
    # 3) Linha do perfil e o artifact.
    await session.delete(target)
    artifact = await session.get(Artifact, artifact_id)
    if artifact is not None:
        await session.delete(artifact)
    await session.commit()

    # 4) Arquivos por último, fora da transação.
    if storage_uris:
        delete_local_storage_files(storage_uris)

    # 5) Tombstone anti-retorno (persistido nas production settings).
    await add_visual_exclusion(
        session, project_id, key=key, label=label, alt_keys=set(keys) - {key}
    )
    return True
