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


from app.storage.service import resolve_storage_path


def _delete_local_storage_file(storage_uri: str) -> bool:
    """Remove um arquivo de storage local se existir."""
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
    "da",
    "do",
    "dos",
    "das",
    "em",
    "na",
    "no",
    "nas",
    "nos",
    "num",
    "numa",
    "para",
    "por",
    "pela",
    "pelo",
    "sem",
    "um",
    "uma",
    "uns",
    "umas",
    "the",
    "an",
    "of",
    "and",
    "or",
    "but",
}
# Verbos de movimento após os quais "para" é preposição ("corre para o farol"),
# não verbo "parar". Com qualquer outra palavra antes, "para" fecha a frase.
_MOTION_VERBS_BEFORE_PARA = {
    "corre",
    "correm",
    "foge",
    "fogem",
    "vai",
    "vao",
    "vão",
    "caminha",
    "caminham",
    "anda",
    "andam",
    "dirige",
    "dirigem",
    "volta",
    "voltam",
    "segue",
    "seguem",
    "entra",
    "entram",
    "sai",
    "saem",
    "avancam",
    "avança",
    "avançam",
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
    return int(segment.source_frame_asset_id is None) + int(segment.final_frame_asset_id is None)


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


async def delete_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
) -> bool:
    """Deleta UM segmento (e seus assets) sem tocar nos demais.

    A cadeia de continuidade NÃO é reencadeada: o segmento seguinte mantém o
    frame inicial que já tem (decisão de produto — apagar só o escolhido). O
    usuário pode regenerar o frame inicial do segmento seguinte se quiser
    reencadear a partir do novo anterior.
    """
    from app.assets.models import Asset, AssetVersion

    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return False
    asset_ids: set[UUID] = set()
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
    for key in ("video_asset_id", "initial_frame_asset_id", "extracted_last_frame_asset_id"):
        raw = meta.get(key)
        if raw:
            try:
                asset_ids.add(UUID(str(raw)))
            except (ValueError, TypeError):
                pass
    storage_uris: list[str] = []
    if asset_ids:
        assets_result = await session.execute(select(Asset).where(Asset.id.in_(asset_ids)))
        for asset in assets_result.scalars():
            uri = str(getattr(asset, "storage_uri", "") or "").strip()
            if uri:
                storage_uris.append(uri)
        await session.execute(delete(AssetVersion).where(AssetVersion.asset_id.in_(asset_ids)))
        await session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    # Desvincula FKs antes de apagar a linha (mesma ordem do delete em massa).
    segment.source_segment_id = None
    segment.source_video_asset_id = None
    segment.source_frame_asset_id = None
    segment.generation_job_id = None
    segment.asset_id = None
    segment.generated_video_asset_id = None
    segment.final_frame_asset_id = None
    await session.flush()
    await session.delete(segment)
    await session.flush()
    for uri in storage_uris:
        _delete_local_storage_file(uri)
    return True


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
        shot_id=payload.shot_id,
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
from app.video_generation.continuous_prompting import (
    concise_video_prompt as _concise_video_prompt,
)


def _refresh_auto_segment_prompt(
    segment: ContinuousVideoSegment,
    *,
    force_custom: bool = False,
    force_regenerate: bool = False,
) -> bool:
    metadata = dict(segment.metadata_json or {})
    if continuous_video_segment_is_approved(segment):
        return False
    if not force_regenerate and (
        getattr(segment, "generated_video_asset_id", None) is not None
        or getattr(segment, "asset_id", None) is not None
        or bool(metadata.get("variants"))
    ):
        return False
    if metadata.get("custom_prompt") is True and not force_custom:
        return False
    shot_spec = metadata.get("shot_generation_spec")
    spec_action = shot_spec.get("action") if isinstance(shot_spec, dict) else ""
    action_source = str(
        metadata.get("storyboard_action")
        or metadata.get("action")
        or spec_action
        or metadata.get("source_text")
        or ""
    ).strip()
    if not action_source:
        return False
    action = _normalize_segment_action(_compact_segment_action(action_source))
    if isinstance(shot_spec, dict):
        shot_spec = {**shot_spec, "action": action}
        metadata["shot_generation_spec"] = shot_spec
    visual_context = metadata.get("visual_context")
    if not isinstance(visual_context, dict):
        visual_context = {}
    prompt = _concise_video_prompt(action, metadata)
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
        # Preserve prompts edited by the user. This action only upgrades prompts
        # that are still managed automatically by the application.
        if not _refresh_auto_segment_prompt(segment, force_regenerate=True):
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


async def _ensure_project_scenes_and_shots(
    session: AsyncSession,
    project_id: UUID,
    script: Any,
) -> tuple[list[Any], dict[UUID, list[Any]]]:
    """Prepare the Shot plan lazily when Video is the first consumer of it."""
    scenes, shots_by_scene = await _project_scenes_and_shots(session, project_id)
    if any(shots_by_scene.values()):
        return scenes, shots_by_scene

    # Storyboards used to prepare scenes and Shots before the Video step. Since
    # both steps now share one screen, Video must own this prerequisite too.
    from app.storytelling.scene_service import generate_scenes_and_shots

    generated_scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if not generated_scenes:
        raise ValueError("Não foi possível gerar cenas e Shots a partir do roteiro atual.")

    scenes, shots_by_scene = await _project_scenes_and_shots(session, project_id)
    if not any(shots_by_scene.values()):
        raise ValueError("As cenas foram criadas, mas nenhum Shot válido foi encontrado.")
    return scenes, shots_by_scene


def _continuous_video_segment_has_user_or_generated_work(
    segment: ContinuousVideoSegment,
) -> bool:
    """Keep completed work intact while an automatic plan is refreshed."""
    metadata = dict(segment.metadata_json or {})
    return bool(
        segment.status == GenerationJobStatus.SUCCEEDED
        or getattr(segment, "asset_id", None)
        or getattr(segment, "generated_video_asset_id", None)
        or getattr(segment, "source_frame_asset_id", None)
        or getattr(segment, "final_frame_asset_id", None)
        or metadata.get("custom_prompt") is True
        or metadata.get("variants")
        or metadata.get("initial_frame_asset_id")
        or metadata.get("final_frame_asset_id")
        or metadata.get("extracted_last_frame_asset_id")
        or metadata.get("video_asset_id")
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
    scenes, shots_by_scene = await _ensure_project_scenes_and_shots(session, project_id, script)
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
                and not _continuous_video_segment_has_user_or_generated_work(segment)
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
        continuity_break = bool(payload.metadata_json.get("continuity_break"))
        if previous_segment is not None and not continuity_break:
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
        elif continuity_break:
            payload.source_segment_id = None
            payload.source_video_asset_id = None
            payload.source_frame_asset_id = None
        existing = existing_segments.get(payload.segment_number)
        if existing is not None and _continuous_video_segment_has_user_or_generated_work(existing):
            preserved_metadata = dict(existing.metadata_json or {})
            preserved_metadata["plan_refresh_preserved"] = True
            preserved_metadata["plan_refresh_reason"] = "user_or_generated_work"
            existing.metadata_json = preserved_metadata
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
            existing.shot_id = payload.shot_id
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


from app.video_generation.continuous_package import (  # noqa: E402,F401
    _prepare_continuous_video_package_fast,
    _prepare_continuous_video_segment_fast,
    emit_continuous_video_segment_event as _emit_continuous_video_segment_event,
    prepare_continuous_video_package,
)


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
from app.video_generation.continuous_frame_service import (  # noqa: E402,F401
    regenerate_continuous_video_segment_frame,
    regenerate_continuous_video_segment_frames,
    remove_continuous_video_segment_frame,
    segment_frame_prompts,
    update_continuous_video_segment_frame_prompt,
)
