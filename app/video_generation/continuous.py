# ruff: noqa: E402, E501, F401, I001

"""Planejamento e preparação do pacote de produção de vídeo.

A etapa de produção de vídeo não gera mais vídeos por IA dentro da aplicação.
Para cada segmento ela prepara um pacote (prompt + frame inicial + frame final)
que o usuário usa para criar o vídeo manualmente manualmente.

Os valores de ``review_status`` são (valores legados são normalizados):
- ``pending``: planejado, aguardando preparação;
- ``preparing`` (legado ``generating``): frames do pacote sendo gerados (imagem);
- ``ready`` (legado ``ready_for_review``): pacote pronto (prompt + frame inicial + frame final);
- ``done`` (legado ``approved``): usuário concluiu o segmento (vídeo criado no pacote);
- ``rejected``: usuário pediu para refazer o pacote;
- ``failed``: erro técnico ao preparar o pacote.
"""

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.enums import GenerationJobStatus
from app.costs.service import assert_project_budget_allows
from app.database.session import AsyncSessionLocal
from app.observability.schemas import OperationalEventCreate
from app.observability.service import emit_project_event
from app.production.service import get_or_create_production_settings
from app.projects.repository import ProjectRepository
from app.video_generation.models import ContinuousVideoPlan, ContinuousVideoSegment
from app.video_generation.schemas import (
    ContinuousVideoPlanCreate,
    ContinuousVideoSegmentCreate,
)
from app.workflows.state_machine import advance_project_status

import os

logger = logging.getLogger(__name__)
ContinuousVideoProgressCallback = Callable[
    [list[dict[str, Any]], Decimal],
    Awaitable[None] | None,
]
ContinuousVideoPackageProgressCallback = Callable[[int, int, str], Awaitable[None] | None]

_CONTINUOUS_FRAME_ASSET_ROLES = {
    "continuous_video_initial_frame",
    "continuous_video_final_frame",
}


def _delete_local_storage_file(storage_uri: str) -> bool:
    """Remove um arquivo de storage local se existir."""
    if not storage_uri or storage_uri.startswith(("http://", "https://", "data:")):
        return False
    try:
        if os.path.exists(storage_uri):
            os.remove(storage_uri)
            return True
    except OSError:
        pass
    return False


CONTINUOUS_PACKAGE_DEFAULT_SOURCE = "manual_package"
CONTINUOUS_VIDEO_DEFAULT_MODEL = "manual_package"
CONTINUOUS_VIDEO_DEFAULT_SEGMENT_SECONDS = 8
CONTINUOUS_VIDEO_MIN_APPROVED_SEGMENTS = 3
CONTINUOUS_VIDEO_FRAME_STRATEGY_CONTINUITY = "continuity"
CONTINUOUS_VIDEO_FRAME_STRATEGIES = {
    CONTINUOUS_VIDEO_FRAME_STRATEGY_CONTINUITY,
}
CONTINUOUS_VIDEO_REVIEW_PENDING = "pending"
CONTINUOUS_VIDEO_REVIEW_PREPARING = "preparing"
CONTINUOUS_VIDEO_REVIEW_READY = "ready"
CONTINUOUS_VIDEO_REVIEW_DONE = "done"
CONTINUOUS_VIDEO_REVIEW_REJECTED = "rejected"
CONTINUOUS_VIDEO_REVIEW_FAILED = "failed"
# Aliases legados: valores gravados antes da transição para o assistente de pacote.
CONTINUOUS_VIDEO_REVIEW_GENERATING = CONTINUOUS_VIDEO_REVIEW_PREPARING
CONTINUOUS_VIDEO_REVIEW_APPROVED = CONTINUOUS_VIDEO_REVIEW_DONE
CONTINUOUS_VIDEO_REVIEW_READY_FOR_REVIEW = CONTINUOUS_VIDEO_REVIEW_READY
CONTINUOUS_VIDEO_REVIEW_STATUSES = {
    CONTINUOUS_VIDEO_REVIEW_PENDING,
    CONTINUOUS_VIDEO_REVIEW_PREPARING,
    CONTINUOUS_VIDEO_REVIEW_READY,
    CONTINUOUS_VIDEO_REVIEW_DONE,
    CONTINUOUS_VIDEO_REVIEW_REJECTED,
    CONTINUOUS_VIDEO_REVIEW_FAILED,
}
# Mapeamento de valores legados para os novos estados do pacote.
_LEGACY_CONTINUOUS_VIDEO_REVIEW_MAP = {
    "generating": CONTINUOUS_VIDEO_REVIEW_PREPARING,
    "ready_for_review": CONTINUOUS_VIDEO_REVIEW_READY,
    "approved": CONTINUOUS_VIDEO_REVIEW_DONE,
}
CONTINUOUS_VIDEO_NEGATIVE_PROMPT = (
    "Nao criar legendas, marcas d'agua, logos, texto na imagem, troca de identidade, "
    "mudanca brusca de figurino, mudanca de local sem acao visivel, cortes abruptos, "
    "flicker, morphing ou deformacao de rosto, maos e objetos."
)
_FRAGILE_SEGMENT_END_WORDS = {
    "a",
    "as",
    "o",
    "os",
    "e",
    "ou",
    "mas",
    "com",
    "de",
    "em",
    "para",
    "por",
    "sem",
    "the",
    "an",
    "of",
    "and",
    "or",
    "but",
}
_ABSTRACT_SEGMENT_TERMS = {
    "alma",
    "agonia",
    "culpa",
    "destino",
    "invisivel",
    "memoria",
    "medo",
    "opressor",
    "saudade",
    "silencio",
    "vazio",
}


def normalize_continuous_video_review_status(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in CONTINUOUS_VIDEO_REVIEW_STATUSES:
        return normalized
    if normalized in _LEGACY_CONTINUOUS_VIDEO_REVIEW_MAP:
        return _LEGACY_CONTINUOUS_VIDEO_REVIEW_MAP[normalized]
    return CONTINUOUS_VIDEO_REVIEW_PENDING


def _set_continuous_video_review_status(
    segment: ContinuousVideoSegment,
    status: str,
    *,
    note: str | None = None,
) -> None:
    previous_status = normalize_continuous_video_review_status(
        getattr(segment, "review_status", None)
    )
    segment.review_status = normalize_continuous_video_review_status(status)
    metadata = dict(segment.metadata_json or {})
    metadata["review_status"] = segment.review_status
    metadata["previous_review_status"] = previous_status
    metadata["review_status_updated_at"] = datetime.now(UTC).isoformat()
    if note is not None:
        metadata["review_note"] = note
    segment.metadata_json = metadata


def _continuous_video_package_frame_work_count(segment: ContinuousVideoSegment) -> int:
    _ = segment
    return 0


def continuous_video_frame_strategy(production_settings: Any) -> str:
    """Always returns continuity strategy — fast/parallel mode was removed."""
    return CONTINUOUS_VIDEO_FRAME_STRATEGY_CONTINUITY


async def _emit_continuous_video_package_progress(
    progress_callback: ContinuousVideoPackageProgressCallback | None,
    completed: int,
    total: int,
    detail: str,
) -> None:
    if progress_callback is None:
        return
    result = progress_callback(completed, total, detail)
    if result is not None:
        await result


def continuous_video_segment_is_done(segment: ContinuousVideoSegment | None) -> bool:
    """True quando o usuário concluiu o segmento (vídeo concluído manualmente)."""
    if segment is None:
        return False
    return (
        normalize_continuous_video_review_status(getattr(segment, "review_status", None))
        == CONTINUOUS_VIDEO_REVIEW_DONE
    )


# Legacy alias for backward compatibility with callers/tests that use the old name.
continuous_video_segment_is_approved = continuous_video_segment_is_done


def continuous_video_request_fingerprint(
    *,
    project_id: UUID,
    segment_number: int,
    prompt: str,
    duration_seconds: int,
    provider: str = CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
    model: str = CONTINUOUS_VIDEO_DEFAULT_MODEL,
    script_fingerprint: str = "",
    visual_fingerprint: str = "",
    source_segment_id: UUID | None = None,
    source_video_asset_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    payload = {
        "duration_seconds": int(duration_seconds),
        "metadata": metadata or {},
        "model": str(model or "").strip(),
        "project_id": str(project_id),
        "prompt": str(prompt or "").strip(),
        "provider": str(provider or "").strip(),
        "script_fingerprint": str(script_fingerprint or "").strip(),
        "segment_number": int(segment_number),
        "source_segment_id": str(source_segment_id) if source_segment_id else None,
        "source_video_asset_id": str(source_video_asset_id) if source_video_asset_id else None,
        "visual_fingerprint": str(visual_fingerprint or "").strip(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def continuous_video_segment_idempotency_key(
    project_id: UUID,
    segment_number: int,
    provider: str,
    model: str,
    request_fingerprint: str,
) -> str:
    raw = f"{project_id}:{segment_number}:{provider}:{model}:{request_fingerprint}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get_or_create_continuous_video_plan(
    session: AsyncSession,
    project_id: UUID,
    payload: ContinuousVideoPlanCreate | None = None,
) -> ContinuousVideoPlan:
    if await ProjectRepository(session).get_project(project_id) is None:
        raise ValueError("Project not found")
    result = await session.execute(
        select(ContinuousVideoPlan).where(ContinuousVideoPlan.project_id == project_id)
    )
    plan = result.scalars().first()
    if plan is not None:
        return plan
    data = payload or ContinuousVideoPlanCreate()
    plan = ContinuousVideoPlan(
        project_id=project_id,
        mode=data.mode,
        target_duration_seconds=data.target_duration_seconds,
        segment_duration_seconds=data.segment_duration_seconds,
        segment_count=data.segment_count,
        status=data.status,
        metadata_json=data.metadata_json,
    )
    session.add(plan)
    await session.flush()
    return plan


async def list_continuous_video_segments(
    session: AsyncSession,
    project_id: UUID,
) -> list[ContinuousVideoSegment]:
    result = await session.execute(
        select(ContinuousVideoSegment)
        .where(ContinuousVideoSegment.project_id == project_id)
        .order_by(ContinuousVideoSegment.segment_number)
    )
    return list(result.scalars())


async def delete_all_continuous_video_segments(
    session: AsyncSession,
    project_id: UUID,
) -> int:
    """Deleta todos os segmentos, prompts e conteudos de producao de video de um projeto.

    Tambem remove assets associados (videos, frames extraidos) do banco e do disco.
    Retorna a quantidade de segmentos removidos.
    """
    from app.assets.models import Asset, AssetVersion

    result = await session.execute(
        select(ContinuousVideoSegment).where(ContinuousVideoSegment.project_id == project_id)
    )
    segments = list(result.scalars())
    count = len(segments)
    if count == 0:
        return 0
    # Collect all asset IDs referenced by segments (columns + metadata_json)
    asset_ids: set[UUID] = set()
    for segment in segments:
        for attr in (
            "asset_id",
            "generated_video_asset_id",
            "source_frame_asset_id",
            "final_frame_asset_id",
            "source_video_asset_id",
        ):
            aid = getattr(segment, attr, None)
            if aid is not None:
                asset_ids.add(aid)
        meta = segment.metadata_json if isinstance(segment.metadata_json, dict) else {}
        for key in (
            "video_asset_id",
            "initial_frame_asset_id",
            "extracted_last_frame_asset_id",
        ):
            raw = meta.get(key)
            if raw:
                try:
                    asset_ids.add(UUID(str(raw)))
                except (ValueError, TypeError):
                    pass
    # Collect storage URIs before deleting DB records
    storage_uris: list[str] = []
    if asset_ids:
        assets_result = await session.execute(select(Asset).where(Asset.id.in_(asset_ids)))
        for asset in assets_result.scalars():
            uri = str(getattr(asset, "storage_uri", "") or "").strip()
            if uri:
                storage_uris.append(uri)
        # Delete asset versions and assets
        await session.execute(delete(AssetVersion).where(AssetVersion.asset_id.in_(asset_ids)))
        await session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    # Unlink FK references to avoid constraint violations
    for segment in segments:
        segment.source_segment_id = None
        segment.source_video_asset_id = None
        segment.source_frame_asset_id = None
        segment.generation_job_id = None
        segment.asset_id = None
        segment.generated_video_asset_id = None
        segment.final_frame_asset_id = None
    await session.flush()
    for segment in segments:
        await session.delete(segment)
    plan_result = await session.execute(
        select(ContinuousVideoPlan).where(ContinuousVideoPlan.project_id == project_id)
    )
    plan = plan_result.scalars().first()
    if plan is not None:
        plan.segment_count = 0
        plan.status = "draft"
        plan.metadata_json = {
            **(plan.metadata_json or {}),
            "segments_cleared": True,
        }
    await session.flush()
    # Delete files from disk AFTER DB commit to maintain consistency
    for uri in storage_uris:
        _delete_local_storage_file(uri)
    return count


async def get_continuous_video_segment_by_number(
    session: AsyncSession,
    project_id: UUID,
    segment_number: int,
) -> ContinuousVideoSegment | None:
    result = await session.execute(
        select(ContinuousVideoSegment).where(
            ContinuousVideoSegment.project_id == project_id,
            ContinuousVideoSegment.segment_number == segment_number,
        )
    )
    return result.scalars().first()


async def get_continuous_video_segment_by_idempotency_key(
    session: AsyncSession,
    idempotency_key: str,
) -> ContinuousVideoSegment | None:
    result = await session.execute(
        select(ContinuousVideoSegment).where(
            ContinuousVideoSegment.idempotency_key == idempotency_key
        )
    )
    return result.scalars().first()


async def create_or_get_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    payload: ContinuousVideoSegmentCreate,
) -> ContinuousVideoSegment:
    if await ProjectRepository(session).get_project(project_id) is None:
        raise ValueError("Project not found")
    provider = payload.provider.strip() or CONTINUOUS_PACKAGE_DEFAULT_SOURCE
    model = payload.model.strip() or CONTINUOUS_VIDEO_DEFAULT_MODEL
    fingerprint = payload.request_fingerprint or continuous_video_request_fingerprint(
        project_id=project_id,
        segment_number=payload.segment_number,
        prompt=payload.prompt,
        duration_seconds=payload.duration_seconds,
        provider=provider,
        model=model,
        source_segment_id=payload.source_segment_id,
        source_video_asset_id=payload.source_video_asset_id,
        metadata=payload.metadata_json,
    )
    idempotency_key = payload.idempotency_key or continuous_video_segment_idempotency_key(
        project_id,
        payload.segment_number,
        provider,
        model,
        fingerprint,
    )
    existing = await get_continuous_video_segment_by_idempotency_key(session, idempotency_key)
    if existing is not None:
        return existing
    segment = ContinuousVideoSegment(
        project_id=project_id,
        script_id=payload.script_id,
        segment_number=payload.segment_number,
        title=payload.title.strip(),
        prompt=payload.prompt.strip(),
        duration_seconds=payload.duration_seconds,
        status=GenerationJobStatus.PENDING,
        review_status=normalize_continuous_video_review_status(payload.review_status),
        provider=provider,
        model=model,
        source_segment_id=payload.source_segment_id,
        source_video_asset_id=payload.source_video_asset_id,
        source_frame_asset_id=payload.source_frame_asset_id,
        request_fingerprint=fingerprint,
        idempotency_key=idempotency_key,
        cost_estimate=payload.cost_estimate,
        metadata_json=payload.metadata_json,
    )
    session.add(segment)
    await session.flush()
    return segment


from app.video_generation.continuous_planning import (
    CONTINUOUS_VIDEO_PROMPT_VERSION,
    _compact_segment_action,
    _normalize_segment_action,
    _segment_prompt,
    build_continuous_video_segment_payloads,
    continuous_video_segment_validation_errors,
    continuous_video_visual_context,
    continuous_video_visual_fingerprint,
)


def _metadata_name_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def _refresh_auto_segment_prompt(
    segment: ContinuousVideoSegment,
    *,
    force_custom: bool = False,
    force_regenerate: bool = False,
) -> bool:
    metadata = dict(segment.metadata_json or {})
    if continuous_video_segment_is_approved(segment):
        return False
    if metadata.get("custom_prompt") is True and not force_custom:
        return False
    source_text = str(metadata.get("source_text") or metadata.get("action") or "").strip()
    if not source_text:
        return False
    action = _normalize_segment_action(_compact_segment_action(source_text))
    visual_context = metadata.get("visual_context")
    if not isinstance(visual_context, dict):
        visual_context = {}
    prompt = _segment_prompt(
        source_text=source_text,
        action=action,
        continuity=str(metadata.get("continuity") or ""),
        characters=_metadata_name_list(metadata.get("characters")),
        locations=_metadata_name_list(metadata.get("locations")),
        visual_context=visual_context,
        segment_number=int(segment.segment_number),
        duration_seconds=int(segment.duration_seconds),
        segment_type="scene_start",
        shot_camera=str(metadata.get("camera_movement") or ""),
        shot_emotion=str(metadata.get("emotion") or ""),
        shot_visual_composition=str(metadata.get("visual_composition") or ""),
    )
    changed = (
        segment.prompt != prompt
        or metadata.get("action") != action
        or metadata.get("custom_prompt") is True
    )
    if (
        not changed
        and not force_regenerate
        and metadata.get("prompt_version") == CONTINUOUS_VIDEO_PROMPT_VERSION
    ):
        return False
    metadata["action"] = action
    metadata["custom_prompt"] = False
    metadata["prompt_version"] = CONTINUOUS_VIDEO_PROMPT_VERSION
    segment.prompt = prompt
    segment.metadata_json = metadata
    provider = str(getattr(segment, "provider", "") or CONTINUOUS_PACKAGE_DEFAULT_SOURCE)
    model = str(getattr(segment, "model", "") or CONTINUOUS_VIDEO_DEFAULT_MODEL)
    segment.request_fingerprint = continuous_video_request_fingerprint(
        project_id=segment.project_id,
        segment_number=int(segment.segment_number),
        prompt=segment.prompt,
        duration_seconds=int(segment.duration_seconds),
        provider=provider,
        model=model,
        script_fingerprint=str(metadata.get("script_fingerprint") or ""),
        visual_fingerprint=str(metadata.get("visual_fingerprint") or ""),
        source_segment_id=getattr(segment, "source_segment_id", None),
        source_video_asset_id=getattr(segment, "source_video_asset_id", None),
        metadata=metadata,
    )
    segment.idempotency_key = continuous_video_segment_idempotency_key(
        segment.project_id,
        int(segment.segment_number),
        provider,
        model,
        segment.request_fingerprint,
    )
    return True


async def regenerate_continuous_video_segment_prompts(
    session: AsyncSession,
    project_id: UUID,
) -> list[ContinuousVideoSegment]:
    segments = await list_continuous_video_segments(session, project_id)
    regenerated: list[ContinuousVideoSegment] = []
    for segment in segments:
        if not _refresh_auto_segment_prompt(segment, force_custom=True, force_regenerate=True):
            continue
        _reset_continuous_video_segment_for_regeneration(
            segment,
            reason="prompts_regenerated",
        )
        segment.source_video_asset_id = None
        segment.source_frame_asset_id = None
        regenerated.append(segment)
    await session.flush()
    return regenerated


from app.video_generation.continuous_queries import (
    _latest_script,
    _project_scenes_and_shots,
    _project_visual_context,
)


async def plan_continuous_video_segments(
    session: AsyncSession,
    project_id: UUID,
    *,
    segment_duration_seconds: int = CONTINUOUS_VIDEO_DEFAULT_SEGMENT_SECONDS,
    provider: str = CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
    model: str = CONTINUOUS_VIDEO_DEFAULT_MODEL,
    replace_existing: bool = False,
) -> tuple[ContinuousVideoPlan, list[ContinuousVideoSegment], dict[int, list[str]]]:
    if await ProjectRepository(session).get_project(project_id) is None:
        raise ValueError("Project not found")
    script = await _latest_script(session, project_id)
    if script is None:
        raise ValueError("Roteiro aprovado nao encontrado para planejar video continuo.")
    scenes, shots_by_scene = await _project_scenes_and_shots(session, project_id)
    visual_context = await _project_visual_context(session, project_id)
    payloads = build_continuous_video_segment_payloads(
        project_id=project_id,
        script=script,
        scenes=scenes,
        shots_by_scene=shots_by_scene,
        visual_context=visual_context,
        segment_duration_seconds=segment_duration_seconds,
        provider=provider,
        model=model,
    )
    plan = await get_or_create_continuous_video_plan(
        session,
        project_id,
        ContinuousVideoPlanCreate(
            mode="continuous_fast",
            target_duration_seconds=int(script.target_duration_seconds or 0),
            segment_duration_seconds=segment_duration_seconds,
            segment_count=len(payloads),
            status="planned",
            metadata_json={
                "script_id": str(script.id),
                "visual_fingerprint": continuous_video_visual_fingerprint(visual_context),
            },
        ),
    )
    plan.target_duration_seconds = int(script.target_duration_seconds or 0)
    plan.segment_duration_seconds = segment_duration_seconds
    plan.segment_count = len(payloads)
    plan.status = "planned"
    plan.metadata_json = {
        **(plan.metadata_json or {}),
        "script_id": str(script.id),
        "visual_fingerprint": continuous_video_visual_fingerprint(visual_context),
    }
    existing_segments = {
        segment.segment_number: segment
        for segment in await list_continuous_video_segments(session, project_id)
    }
    if replace_existing:
        max_segment_number = len(payloads)
        stale_segments = [
            segment
            for segment_number, segment in existing_segments.items()
            if (
                segment_number > max_segment_number
                and segment.status != GenerationJobStatus.SUCCEEDED
            )
        ]
        stale_segment_ids = {segment.id for segment in stale_segments}
        for segment in existing_segments.values():
            if segment.source_segment_id in stale_segment_ids:
                segment.source_segment_id = None
                segment.source_video_asset_id = None
                segment.source_frame_asset_id = None
        if stale_segment_ids:
            await session.flush()
        for segment_number, segment in list(existing_segments.items()):
            if segment.id in stale_segment_ids:
                await session.delete(segment)
                existing_segments.pop(segment_number, None)
    planned_segments: list[ContinuousVideoSegment] = []
    previous_segment: ContinuousVideoSegment | None = None
    for payload in payloads:
        if previous_segment is not None:
            payload.source_segment_id = previous_segment.id
            payload.source_video_asset_id = previous_segment.asset_id
            payload.source_frame_asset_id = previous_segment.final_frame_asset_id
            payload.metadata_json = {
                **payload.metadata_json,
                "source_segment_id": str(previous_segment.id),
                "source_video_asset_id": (
                    str(previous_segment.asset_id) if previous_segment.asset_id else None
                ),
                "source_frame_asset_id": (
                    str(previous_segment.final_frame_asset_id)
                    if previous_segment.final_frame_asset_id
                    else None
                ),
            }
        existing = existing_segments.get(payload.segment_number)
        if existing is not None and existing.status == GenerationJobStatus.SUCCEEDED:
            planned_segments.append(existing)
            previous_segment = existing
            continue
        if existing is not None and not replace_existing:
            planned_segments.append(existing)
            previous_segment = existing
            continue
        if existing is not None:
            existing.title = payload.title.strip()
            existing.script_id = payload.script_id
            existing.prompt = payload.prompt.strip()
            existing.duration_seconds = payload.duration_seconds
            existing.review_status = normalize_continuous_video_review_status(payload.review_status)
            existing.provider = payload.provider
            existing.model = payload.model
            existing.source_segment_id = payload.source_segment_id
            existing.source_video_asset_id = payload.source_video_asset_id
            existing.source_frame_asset_id = payload.source_frame_asset_id
            existing.final_frame_asset_id = None
            existing.generated_video_asset_id = None
            existing.request_fingerprint = payload.request_fingerprint or ""
            existing.idempotency_key = (
                payload.idempotency_key
                or continuous_video_segment_idempotency_key(
                    project_id,
                    payload.segment_number,
                    payload.provider,
                    payload.model,
                    existing.request_fingerprint,
                )
            )
            existing.metadata_json = payload.metadata_json
            existing.status = GenerationJobStatus.PENDING
            segment = existing
        else:
            segment = await create_or_get_continuous_video_segment(session, project_id, payload)
        planned_segments.append(segment)
        previous_segment = segment
    validation_errors = {
        segment.segment_number: errors
        for segment in planned_segments
        for errors in [continuous_video_segment_validation_errors(segment)]
        if errors
    }
    await session.flush()
    return plan, planned_segments, validation_errors


from app.video_generation.continuous_frames import (
    _ensure_package_initial_frame,
    _generate_segment_final_frame,
    _generate_segment_initial_frame,
)


async def _emit_continuous_video_segment_event(
    session: AsyncSession,
    *,
    segment: ContinuousVideoSegment,
    status: str,
    provider: str,
    model: str,
    message: str,
    estimated_cost: Decimal | None = None,
    details: dict[str, Any] | None = None,
    operation: str = "manual_package",
) -> None:
    payload = {
        "segment_id": str(segment.id),
        "segment_number": segment.segment_number,
        "duration_seconds": segment.duration_seconds,
    }
    if details:
        payload.update(details)
    await emit_project_event(
        session,
        OperationalEventCreate(
            project_id=segment.project_id,
            job_id=segment.generation_job_id,
            event_type="continuous_video_segment",
            status=status,
            provider=provider,
            model=model,
            operation=operation,
            estimated_cost=estimated_cost,
            message=message,
            details=payload,
        ),
    )


async def _prepare_continuous_video_segment_fast(
    project_id: UUID,
    segment_id: UUID,
) -> tuple[ContinuousVideoSegment | None, list[str]]:
    async with AsyncSessionLocal() as session:
        segment = await session.get(ContinuousVideoSegment, segment_id)
        if segment is None or segment.project_id != project_id:
            return None, ["Segmento nao encontrado."]
        production_settings = await get_or_create_production_settings(session, project_id)
        segment.review_status = CONTINUOUS_VIDEO_REVIEW_GENERATING
        segment.status = GenerationJobStatus.RUNNING
        metadata = dict(segment.metadata_json or {})
        metadata.pop("error", None)
        metadata.pop("package_error", None)
        metadata["frame_strategy"] = CONTINUOUS_VIDEO_FRAME_STRATEGY_CONTINUITY
        segment.metadata_json = metadata
        await session.commit()
        try:
            if segment.source_frame_asset_id is None:
                await _generate_segment_initial_frame(
                    session,
                    project_id,
                    segment,
                    production_settings,
                )
                await session.commit()
                await session.refresh(segment)
            await _generate_segment_final_frame(
                session,
                project_id,
                segment,
                production_settings,
            )
            _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_READY)
            segment.status = GenerationJobStatus.SUCCEEDED
            metadata = dict(segment.metadata_json or {})
            metadata.pop("error", None)
            metadata.pop("package_error", None)
            metadata["package_ready_at"] = datetime.now(UTC).isoformat()
            metadata["frame_strategy"] = CONTINUOUS_VIDEO_FRAME_STRATEGY_CONTINUITY
            segment.metadata_json = metadata
            await _emit_continuous_video_segment_event(
                session,
                segment=segment,
                status="ready",
                provider=CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
                model=CONTINUOUS_VIDEO_DEFAULT_MODEL,
                message="Frames do pacote prontos: gere os vídeos na aba Vídeo.",
            )
            await session.commit()
            await session.refresh(segment)
            return segment, []
        except Exception as exc:
            logger.warning(
                "continuous_video_package_failed project_id=%s segment_number=%s reason=%s",
                project_id,
                segment.segment_number,
                exc,
            )
            error_message = str(exc)
            segment.status = GenerationJobStatus.FAILED
            segment.review_status = CONTINUOUS_VIDEO_REVIEW_FAILED
            metadata = dict(segment.metadata_json or {})
            metadata["error"] = error_message
            metadata["package_error"] = error_message
            metadata["failed_at"] = datetime.now(UTC).isoformat()
            metadata["frame_strategy"] = CONTINUOUS_VIDEO_FRAME_STRATEGY_CONTINUITY
            segment.metadata_json = metadata
            await _emit_continuous_video_segment_event(
                session,
                segment=segment,
                status="failed",
                provider=CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
                model=CONTINUOUS_VIDEO_DEFAULT_MODEL,
                message=error_message,
            )
            await session.commit()
            return segment, [error_message]


async def _prepare_continuous_video_package_fast(
    session: AsyncSession,
    project_id: UUID,
    segments_to_prepare: list[ContinuousVideoSegment],
    validation_errors: dict[int, list[str]],
    progress_callback: ContinuousVideoPackageProgressCallback | None,
) -> tuple[list[ContinuousVideoSegment], dict[int, list[str]]]:
    app_settings = get_settings()
    concurrency = max(1, min(int(getattr(app_settings, "video_generation_concurrency", 2) or 2), 4))
    semaphore = asyncio.Semaphore(concurrency)
    progress_lock = asyncio.Lock()
    completed_frame_work = 0
    total_frame_work = sum(
        _continuous_video_package_frame_work_count(segment) for segment in segments_to_prepare
    )
    if total_frame_work > 0:
        await _emit_continuous_video_package_progress(
            progress_callback,
            0,
            total_frame_work,
            f"Agora: preparando frames em modo rapido ({concurrency} em paralelo).",
        )

    async def mark_progress(increment: int, detail: str) -> None:
        nonlocal completed_frame_work
        async with progress_lock:
            completed_frame_work += increment
            await _emit_continuous_video_package_progress(
                progress_callback,
                completed_frame_work,
                total_frame_work,
                detail,
            )

    async def run_segment(segment: ContinuousVideoSegment) -> ContinuousVideoSegment | None:
        frame_count = _continuous_video_package_frame_work_count(segment)
        async with semaphore:
            await _emit_continuous_video_package_progress(
                progress_callback,
                completed_frame_work,
                total_frame_work,
                f"Agora: preparando Segmento {segment.segment_number:02d} em modo rapido.",
            )
            try:
                prepared, errors = await _prepare_continuous_video_segment_fast(
                    project_id,
                    segment.id,
                )
            except Exception as exc:
                logger.warning(
                    "continuous_video_segment_prepare_failed project_id=%s segment=%s: %s",
                    project_id,
                    segment.segment_number,
                    exc,
                )
                validation_errors[segment.segment_number] = [str(exc)]
                await mark_progress(
                    frame_count,
                    f"Segmento {segment.segment_number:02d} falhou.",
                )
                return None
            if errors:
                validation_errors[segment.segment_number] = errors
            await mark_progress(
                frame_count,
                f"Segmento {segment.segment_number:02d} processado.",
            )
            return prepared

    prepared = [
        segment
        for segment in await asyncio.gather(
            *(run_segment(segment) for segment in segments_to_prepare)
        )
        if segment is not None
    ]
    refreshed = await list_continuous_video_segments(session, project_id)
    refreshed_by_id = {segment.id: segment for segment in refreshed}
    return [refreshed_by_id.get(segment.id, segment) for segment in prepared], validation_errors


async def prepare_continuous_video_package(
    session: AsyncSession,
    project_id: UUID,
    *,
    segment_ids: list[UUID] | None = None,
    progress_callback: ContinuousVideoPackageProgressCallback | None = None,
) -> tuple[list[ContinuousVideoSegment], dict[int, list[str]]]:
    """Valida e prepara prompts de vídeo sem gerar imagens auxiliares."""
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        raise ValueError("Projeto nao encontrado.")
    segments = await list_continuous_video_segments(session, project_id)
    if not segments:
        _plan, segments, _plan_validation_errors = await plan_continuous_video_segments(
            session,
            project_id,
            replace_existing=False,
        )
        if _plan_validation_errors:
            first_segment_number = min(_plan_validation_errors)
            raise ValueError(
                "Revise o planejamento antes de preparar: "
                + "; ".join(_plan_validation_errors[first_segment_number])
            )
    if segment_ids:
        selected_ids = set(segment_ids)
        segments = [segment for segment in segments if segment.id in selected_ids]
    if not segments:
        return [], {}
    prepared_without_images: list[ContinuousVideoSegment] = []
    prompt_validation_errors: dict[int, list[str]] = {}
    for segment in segments:
        if _refresh_auto_segment_prompt(segment):
            await session.flush()
        errors = continuous_video_segment_validation_errors(segment)
        if errors:
            prompt_validation_errors[segment.segment_number] = errors
            continue
        segment.status = GenerationJobStatus.SUCCEEDED
        _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_READY)
        metadata = dict(segment.metadata_json or {})
        metadata.pop("error", None)
        metadata.pop("package_error", None)
        metadata["package_ready_at"] = datetime.now(UTC).isoformat()
        metadata["package_mode"] = "text_prompt_only"
        metadata["frame_strategy"] = "extracted_previous_video_frame"
        segment.metadata_json = metadata
        prepared_without_images.append(segment)
    await session.flush()
    await _emit_continuous_video_package_progress(
        progress_callback,
        len(prepared_without_images),
        len(segments),
        "Prompts de vídeo preparados sem geração de imagens.",
    )
    return prepared_without_images, prompt_validation_errors

    # Compatibilidade de leitura para pacotes antigos abaixo deste ponto.
    production_settings = await get_or_create_production_settings(session, project_id)
    prepared: list[ContinuousVideoSegment] = []
    segments_to_prepare: list[ContinuousVideoSegment] = []
    validation_errors: dict[int, list[str]] = {}
    for segment in segments:
        if _refresh_auto_segment_prompt(segment):
            await session.flush()
        existing_errors = continuous_video_segment_validation_errors(segment)
        if existing_errors:
            validation_errors[segment.segment_number] = existing_errors
            continue
        if (
            segment.review_status
            in {
                CONTINUOUS_VIDEO_REVIEW_READY,
                CONTINUOUS_VIDEO_REVIEW_APPROVED,
            }
            and segment.source_frame_asset_id is not None
        ):
            prepared.append(segment)
            continue
        if _continuous_video_package_frame_work_count(segment) == 0:
            # Garante que frames existentes ou referências anteriores sejam vinculados
            await _ensure_package_initial_frame(
                session,
                project_id,
                segment,
                production_settings,
            )
            prepared.append(segment)
            continue
        segments_to_prepare.append(segment)

    total_frame_work = sum(
        _continuous_video_package_frame_work_count(segment) for segment in segments_to_prepare
    )
    if total_frame_work > 0:
        await _emit_continuous_video_package_progress(
            progress_callback,
            0,
            total_frame_work,
            "Agora: preparando frame inicial do primeiro segmento.",
        )
    completed_frame_work = 0
    for segment in segments_to_prepare:
        segment_title = f"Segmento {segment.segment_number:02d}"
        segment.review_status = CONTINUOUS_VIDEO_REVIEW_GENERATING
        segment.status = GenerationJobStatus.RUNNING
        metadata = dict(segment.metadata_json or {})
        metadata.pop("error", None)
        metadata.pop("package_error", None)
        segment.metadata_json = metadata
        await session.flush()
        try:
            needs_initial_frame = (
                segment.segment_number <= 1 and segment.source_frame_asset_id is None
            )
            if needs_initial_frame:
                await _emit_continuous_video_package_progress(
                    progress_callback,
                    completed_frame_work,
                    total_frame_work,
                    f"Agora: preparando frame inicial do {segment_title}.",
                )
            await _ensure_package_initial_frame(
                session,
                project_id,
                segment,
                production_settings,
            )
            if needs_initial_frame and segment.source_frame_asset_id is not None:
                await session.commit()
                await session.refresh(segment)
                completed_frame_work += 1
                await _emit_continuous_video_package_progress(
                    progress_callback,
                    completed_frame_work,
                    total_frame_work,
                    f"Frame inicial do {segment_title} pronto.",
                )
            else:
                await session.commit()
                await session.refresh(segment)
        except Exception as exc:
            logger.warning(
                "continuous_video_package_failed project_id=%s segment_number=%s reason=%s",
                project_id,
                segment.segment_number,
                exc,
            )
            error_message = str(exc)
            segment.status = GenerationJobStatus.FAILED
            segment.review_status = CONTINUOUS_VIDEO_REVIEW_FAILED
            metadata = dict(segment.metadata_json or {})
            metadata["error"] = error_message
            metadata["package_error"] = error_message
            metadata["failed_at"] = datetime.now(UTC).isoformat()
            segment.metadata_json = metadata
            validation_errors[segment.segment_number] = [error_message]
            await _emit_continuous_video_segment_event(
                session,
                segment=segment,
                status="failed",
                provider=CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
                model=CONTINUOUS_VIDEO_DEFAULT_MODEL,
                message=error_message,
            )
            await session.flush()
            continue
        _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_READY)
        segment.status = GenerationJobStatus.SUCCEEDED
        metadata = dict(segment.metadata_json or {})
        metadata.pop("error", None)
        metadata.pop("package_error", None)
        metadata["package_ready_at"] = datetime.now(UTC).isoformat()
        segment.metadata_json = metadata
        prepared.append(segment)
        await _emit_continuous_video_segment_event(
            session,
            segment=segment,
            status="ready",
            provider=CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
            model=CONTINUOUS_VIDEO_DEFAULT_MODEL,
            message="Pacote de vídeo pronto: copie o prompt e use os frames.",
        )
        await session.flush()
    await session.commit()
    for item in prepared:
        await session.refresh(item)
    return prepared, validation_errors


from app.video_generation.continuous_review import (
    _reset_continuous_video_segment_for_regeneration,
    approve_continuous_video_segment,
    attach_continuous_video_segment_result,
    continuous_video_segment_continuity_summary,
    extract_continuous_video_segment_frames,
    generate_continuous_video_segment,
    generate_continuous_video_segments,
    generate_next_continuous_video_segment,
    invalidate_continuous_video_downstream_segments,
    mark_continuous_video_segment_done,
    regenerate_rejected_continuous_video_segment,
    reject_continuous_video_segment,
    retry_failed_continuous_video_segment,
    update_continuous_video_segment_prompt,
)


async def _delete_continuous_video_frame_asset_if_unshared(
    session: AsyncSession,
    *,
    asset_id: UUID,
    segment_id: UUID,
) -> str | None:
    from app.assets.models import Asset, AssetVersion

    asset = await session.get(Asset, asset_id)
    if asset is None:
        return None
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    if (
        str(metadata.get("segment_id") or "") != str(segment_id)
        or metadata.get("technical_role") not in _CONTINUOUS_FRAME_ASSET_ROLES
    ):
        return None

    shared_result = await session.execute(
        select(ContinuousVideoSegment.id)
        .where(
            ContinuousVideoSegment.id != segment_id,
            or_(
                ContinuousVideoSegment.source_frame_asset_id == asset_id,
                ContinuousVideoSegment.final_frame_asset_id == asset_id,
            ),
        )
        .limit(1)
    )
    if shared_result.scalars().first() is not None:
        return None

    storage_uri = str(asset.storage_uri or "")
    await session.execute(delete(AssetVersion).where(AssetVersion.asset_id == asset_id))
    await session.delete(asset)
    return storage_uri


async def _continuous_video_frame_asset_belongs_to_segment(
    session: AsyncSession,
    *,
    asset_id: UUID,
    segment_id: UUID,
) -> bool:
    from app.assets.models import Asset

    asset = await session.get(Asset, asset_id)
    if asset is None:
        return False
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    return (
        str(metadata.get("segment_id") or "") == str(segment_id)
        and metadata.get("technical_role") in _CONTINUOUS_FRAME_ASSET_ROLES
    )


def _set_continuous_video_segment_package_status(segment: ContinuousVideoSegment) -> None:
    metadata = dict(segment.metadata_json or {})
    if segment.source_frame_asset_id is not None and segment.final_frame_asset_id is not None:
        _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_READY)
        metadata = dict(segment.metadata_json or {})
        segment.status = GenerationJobStatus.SUCCEEDED
        metadata.pop("error", None)
        metadata.pop("package_error", None)
        metadata["package_ready_at"] = datetime.now(UTC).isoformat()
    else:
        segment.review_status = CONTINUOUS_VIDEO_REVIEW_PENDING
        segment.status = GenerationJobStatus.PENDING
        metadata.pop("package_ready_at", None)
        metadata["review_status"] = CONTINUOUS_VIDEO_REVIEW_PENDING
    segment.metadata_json = metadata


async def remove_continuous_video_segment_frame(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    frame_kind: str,
) -> ContinuousVideoSegment | None:
    """Detaches one frame from a segment and deletes it only when it is unshared."""
    normalized_kind = str(frame_kind or "").strip().lower()
    if normalized_kind not in {"initial", "final"}:
        raise ValueError("frame_kind deve ser 'initial' ou 'final'.")
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None

    metadata = dict(segment.metadata_json or {})
    removed_at = datetime.now(UTC).isoformat()
    old_asset_id = (
        segment.source_frame_asset_id
        if normalized_kind == "initial"
        else segment.final_frame_asset_id
    )
    if normalized_kind == "initial":
        segment.source_frame_asset_id = None
        metadata.pop("initial_frame_asset_id", None)
        metadata.pop("initial_frame_storage_uri", None)
        metadata.pop("initial_frame_reference_uris", None)
        metadata["initial_frame_removed_manually"] = True
        metadata["initial_frame_removed_at"] = removed_at
    else:
        segment.final_frame_asset_id = None
        metadata.pop("final_frame_asset_id", None)
        metadata.pop("final_frame_storage_uri", None)
        metadata.pop("final_frame_reference_uris", None)
        metadata["final_frame_removed_manually"] = True
        metadata["final_frame_removed_at"] = removed_at
    metadata.pop("error", None)
    metadata.pop("package_error", None)
    segment.metadata_json = metadata
    _set_continuous_video_segment_package_status(segment)
    await session.flush()

    if old_asset_id is not None:
        deleted_storage_uri = await _delete_continuous_video_frame_asset_if_unshared(
            session,
            asset_id=old_asset_id,
            segment_id=segment.id,
        )
        if deleted_storage_uri:
            from app.storage.service import delete_local_storage_files

            delete_local_storage_files([deleted_storage_uri])

    if normalized_kind == "final":
        await invalidate_continuous_video_downstream_segments(
            session,
            project_id,
            segment.segment_number,
            reason="upstream_final_frame_removed",
        )
    await _emit_continuous_video_segment_event(
        session,
        segment=segment,
        status="pending",
        provider=CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
        model=CONTINUOUS_VIDEO_DEFAULT_MODEL,
        message=(
            "Frame inicial removido manualmente."
            if normalized_kind == "initial"
            else "Frame final removido manualmente."
        ),
    )
    await session.commit()
    await session.refresh(segment)
    return segment


async def regenerate_continuous_video_segment_frame(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    frame_kind: str,
) -> ContinuousVideoSegment | None:
    """Regenerates only one frame from a segment package."""
    normalized_kind = str(frame_kind or "").strip().lower()
    if normalized_kind not in {"initial", "final"}:
        raise ValueError("frame_kind deve ser 'initial' ou 'final'.")
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None

    metadata = dict(segment.metadata_json or {})
    old_asset_id = (
        segment.source_frame_asset_id
        if normalized_kind == "initial"
        else segment.final_frame_asset_id
    )
    if (
        normalized_kind == "initial"
        and segment.segment_number > 1
        and old_asset_id is not None
        and not await _continuous_video_frame_asset_belongs_to_segment(
            session,
            asset_id=old_asset_id,
            segment_id=segment.id,
        )
    ):
        raise ValueError(
            "O frame inicial deste segmento vem do frame final do segmento anterior. "
            "Regere o frame final do segmento anterior para manter a continuidade."
        )

    if normalized_kind == "initial":
        segment.source_frame_asset_id = None
        metadata.pop("initial_frame_asset_id", None)
        metadata.pop("initial_frame_storage_uri", None)
        metadata.pop("initial_frame_reference_uris", None)
    else:
        segment.final_frame_asset_id = None
        metadata.pop("final_frame_asset_id", None)
        metadata.pop("final_frame_storage_uri", None)
        metadata.pop("final_frame_reference_uris", None)
    metadata.pop("error", None)
    metadata.pop("package_error", None)
    segment.metadata_json = metadata
    segment.review_status = CONTINUOUS_VIDEO_REVIEW_PREPARING
    segment.status = GenerationJobStatus.RUNNING
    await session.flush()

    if old_asset_id is not None:
        deleted_storage_uri = await _delete_continuous_video_frame_asset_if_unshared(
            session,
            asset_id=old_asset_id,
            segment_id=segment.id,
        )
        if deleted_storage_uri:
            from app.storage.service import delete_local_storage_files

            delete_local_storage_files([deleted_storage_uri])

    production_settings = await get_or_create_production_settings(session, project_id)
    try:
        if normalized_kind == "initial":
            if old_asset_id is None and segment.segment_number > 1:
                await _ensure_package_initial_frame(
                    session,
                    project_id,
                    segment,
                    production_settings,
                )
            else:
                await _generate_segment_initial_frame(
                    session,
                    project_id,
                    segment,
                    production_settings,
                )
            message = "Frame inicial regenerado com sucesso."
        else:
            if segment.source_frame_asset_id is None:
                raise ValueError("Gere o frame inicial antes de gerar o frame final.")
            await _generate_segment_final_frame(
                session,
                project_id,
                segment,
                production_settings,
            )
            await invalidate_continuous_video_downstream_segments(
                session,
                project_id,
                segment.segment_number,
                reason="upstream_final_frame_regenerated",
            )
            message = "Frame final regenerado com sucesso."

        _set_continuous_video_segment_package_status(segment)
        await _emit_continuous_video_segment_event(
            session,
            segment=segment,
            status="ready" if segment.review_status == CONTINUOUS_VIDEO_REVIEW_READY else "pending",
            provider=CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
            model=CONTINUOUS_VIDEO_DEFAULT_MODEL,
            message=message,
        )
        await session.commit()
        await session.refresh(segment)
        return segment
    except Exception as exc:
        logger.warning(
            "regenerate_segment_frame_failed project_id=%s segment=%s frame_kind=%s: %s",
            project_id,
            segment.segment_number,
            normalized_kind,
            exc,
        )
        segment.status = GenerationJobStatus.FAILED
        segment.review_status = CONTINUOUS_VIDEO_REVIEW_FAILED
        error_metadata = dict(segment.metadata_json or {})
        error_metadata["error"] = str(exc)
        error_metadata["package_error"] = str(exc)
        error_metadata["failed_at"] = datetime.now(UTC).isoformat()
        segment.metadata_json = error_metadata
        await session.commit()
        raise


async def regenerate_continuous_video_segment_frames(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
) -> ContinuousVideoSegment | None:
    """Generates only missing frames for a single segment."""
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    if _continuous_video_package_frame_work_count(segment) == 0:
        return segment
    prepared, validation_errors = await prepare_continuous_video_package(
        session,
        project_id,
        segment_ids=[segment_id],
    )
    if validation_errors:
        first_segment_number = min(validation_errors)
        raise ValueError("; ".join(validation_errors[first_segment_number]))
    return prepared[0] if prepared else segment


async def update_continuous_video_segment_frame_prompt(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    initial_frame_prompt: str | None = None,
    final_frame_prompt: str | None = None,
) -> ContinuousVideoSegment | None:
    """Saves custom frame prompt overrides into the segment metadata.

    When initial_frame_prompt or final_frame_prompt is provided (non-None),
    the value is stored as an override in metadata_json. When set to empty
    string, the override is cleared (revert to auto-generated prompt).
    """
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    metadata = dict(segment.metadata_json or {})
    if initial_frame_prompt is not None:
        if initial_frame_prompt.strip():
            metadata["initial_frame_prompt_override"] = initial_frame_prompt.strip()
        else:
            metadata.pop("initial_frame_prompt_override", None)
    if final_frame_prompt is not None:
        if final_frame_prompt.strip():
            metadata["final_frame_prompt_override"] = final_frame_prompt.strip()
        else:
            metadata.pop("final_frame_prompt_override", None)
    segment.metadata_json = metadata
    await session.commit()
    await session.refresh(segment)
    return segment


def segment_frame_prompts(segment: ContinuousVideoSegment) -> dict[str, str]:
    """Legacy UI compatibility: synthetic frame prompts no longer exist."""
    _ = segment
    return {"initial": "", "final": ""}
