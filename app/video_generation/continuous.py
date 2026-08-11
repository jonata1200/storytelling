import asyncio
import hashlib
import json
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from inspect import isawaitable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.config.provider_policy import effective_provider_for_channel
from app.config.settings import get_settings
from app.core.enums import (
    AssetKind,
    CostEntryType,
    GenerationJobStatus,
    GenerationJobType,
    ProjectStatus,
)
from app.costs.models import CostEntry
from app.costs.service import (
    assert_project_budget_allows,
    cost_audit_metadata,
    estimate_operation_cost,
    final_budget_cost,
)
from app.observability.schemas import OperationalEventCreate
from app.observability.service import emit_project_event
from app.production.service import (
    get_or_create_production_settings,
    normalize_video_resolution,
)
from app.projects.repository import ProjectRepository
from app.providers.video.google_ai import GoogleAIVideoProvider
from app.providers.video.types import VideoProvider, VideoRequest, VideoResult
from app.storage.service import apply_asset_storage_metadata
from app.storytelling.models import Scene, Script, Shot
from app.video_generation.models import ContinuousVideoPlan, ContinuousVideoSegment, GenerationJob
from app.video_generation.retry import exponential_backoff_seconds
from app.video_generation.schemas import (
    ContinuousVideoPlanCreate,
    ContinuousVideoSegmentCreate,
)
from app.visual_bible.models import Character, Location, Prop
from app.workflows.state_machine import advance_project_status

logger = logging.getLogger(__name__)
ContinuousVideoProgressCallback = Callable[
    [list[dict[str, Any]], Decimal],
    Awaitable[None] | None,
]

CONTINUOUS_VIDEO_DEFAULT_PROVIDER = "google_ai"
CONTINUOUS_VIDEO_FAST_MODEL = "veo-3.1-fast-generate-preview"
CONTINUOUS_VIDEO_DEFAULT_SEGMENT_SECONDS = 7
CONTINUOUS_VIDEO_NEGATIVE_PROMPT = (
    "Nao criar legendas, marcas d'agua, logos, texto na imagem, troca de identidade, "
    "mudanca brusca de figurino, mudanca de local sem acao visivel, cortes abruptos, "
    "flicker, morphing ou deformacao de rosto, maos e objetos."
)


def continuous_video_request_fingerprint(
    *,
    project_id: UUID,
    segment_number: int,
    prompt: str,
    duration_seconds: int,
    provider: str = CONTINUOUS_VIDEO_DEFAULT_PROVIDER,
    model: str = CONTINUOUS_VIDEO_FAST_MODEL,
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


def continuous_video_segment_is_stale_running(
    segment: ContinuousVideoSegment,
    *,
    after_minutes: int = 10,
) -> bool:
    if segment.status != GenerationJobStatus.RUNNING:
        return False
    updated_at = segment.updated_at or segment.created_at
    if updated_at is None:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - updated_at >= timedelta(minutes=after_minutes)


def continuous_video_segment_needs_generation(
    segment: ContinuousVideoSegment | None,
    *,
    retry_failed: bool = False,
) -> bool:
    if segment is None:
        return True
    if continuous_video_segment_is_stale_running(segment):
        return True
    if segment.status in {GenerationJobStatus.PENDING, GenerationJobStatus.RETRY_SCHEDULED}:
        return True
    if retry_failed and segment.status == GenerationJobStatus.FAILED:
        return True
    return False


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
    provider = payload.provider.strip() or CONTINUOUS_VIDEO_DEFAULT_PROVIDER
    model = payload.model.strip() or CONTINUOUS_VIDEO_FAST_MODEL
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
        segment_number=payload.segment_number,
        title=payload.title.strip(),
        prompt=payload.prompt.strip(),
        duration_seconds=payload.duration_seconds,
        status=GenerationJobStatus.PENDING,
        provider=provider,
        model=model,
        source_segment_id=payload.source_segment_id,
        source_video_asset_id=payload.source_video_asset_id,
        request_fingerprint=fingerprint,
        idempotency_key=idempotency_key,
        cost_estimate=payload.cost_estimate,
        metadata_json=payload.metadata_json,
    )
    if segment.cost_estimate <= Decimal("0"):
        segment.cost_estimate = estimate_operation_cost(
            "image_to_video",
            Decimal(segment.duration_seconds),
            provider=provider,
            model=model,
        ).estimated
    session.add(segment)
    await session.flush()
    return segment


def continuous_video_segment_validation_errors(segment: ContinuousVideoSegment) -> list[str]:
    errors: list[str] = []
    prompt = str(segment.prompt or "").strip()
    metadata = segment.metadata_json if isinstance(segment.metadata_json, dict) else {}
    if segment.segment_number <= 0:
        errors.append("numero de segmento invalido")
    if segment.duration_seconds <= 0:
        errors.append("duracao invalida")
    if len(prompt.split()) < 20:
        errors.append("prompt generico demais")
    if not metadata.get("action"):
        errors.append("acao principal ausente")
    if not metadata.get("continuity"):
        errors.append("continuidade ausente")
    visual_context = metadata.get("visual_context")
    if not isinstance(visual_context, dict) or not any(visual_context.values()):
        errors.append("Biblioteca Visual ausente")
    return errors


def _profile_prompt(profile: dict) -> str:
    for key in (
        "canonical_prompt",
        "description",
        "narrative_profile",
        "visual_profile",
        "name",
    ):
        value = profile.get(key)
        if isinstance(value, dict):
            text = ", ".join(
                str(item).strip()
                for item in value.values()
                if isinstance(item, str) and item.strip()
            )
        else:
            text = str(value or "").strip()
        if text:
            return text
    return ""


def _visual_items_summary(items: list[Any], *, label: str, limit: int = 6) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for item in items[:limit]:
        profile = getattr(item, "canonical_profile", {}) or {}
        name = str(getattr(item, "name", "") or profile.get("name") or "").strip()
        if not name:
            continue
        prompt = _profile_prompt(profile)
        summaries.append({"name": name, "label": label, "prompt": prompt})
    return summaries


def continuous_video_visual_context(
    characters: list[Any],
    locations: list[Any],
    props: list[Any],
) -> dict[str, list[dict[str, str]]]:
    return {
        "characters": _visual_items_summary(characters, label="personagem"),
        "locations": _visual_items_summary(locations, label="local"),
        "props": _visual_items_summary(props, label="objeto"),
    }


def continuous_video_visual_fingerprint(visual_context: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(visual_context, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _names_present(text: str, visual_items: list[dict[str, str]]) -> list[str]:
    normalized = text.casefold()
    found = [
        item["name"]
        for item in visual_items
        if item.get("name") and item["name"].casefold() in normalized
    ]
    return found or [item["name"] for item in visual_items[:3] if item.get("name")]


def _chunk_text_fallback(content: str, segment_count: int) -> list[str]:
    paragraphs = [part.strip() for part in content.splitlines() if part.strip()]
    if not paragraphs:
        paragraphs = [content.strip()]
    if len(paragraphs) >= segment_count:
        chunk_size = max(1, math.ceil(len(paragraphs) / segment_count))
        chunks = [
            "\n".join(paragraphs[index : index + chunk_size]).strip()
            for index in range(0, len(paragraphs), chunk_size)
        ]
        while len(chunks) < segment_count:
            chunks.append(chunks[-1])
        return chunks[:segment_count]
    words = content.split()
    if not words:
        return ["acao visual principal do roteiro"] * segment_count
    chunk_size = max(1, math.ceil(len(words) / segment_count))
    chunks = [
        " ".join(words[index : index + chunk_size]).strip()
        for index in range(0, len(words), chunk_size)
    ]
    while len(chunks) < segment_count:
        chunks.append(chunks[-1])
    return chunks[:segment_count]


def _ordered_shot_units(scenes: list[Scene], shots_by_scene: dict[UUID, list[Shot]]) -> list[dict]:
    units: list[dict] = []
    for scene in sorted(scenes, key=lambda item: int(item.scene_number or 0)):
        shots = sorted(
            shots_by_scene.get(scene.id, []),
            key=lambda item: int(item.shot_number or 0),
        )
        if not shots:
            units.append(
                {
                    "scene_number": scene.scene_number,
                    "shot_numbers": [],
                    "duration": int(scene.duration_seconds or 0),
                    "text": f"{scene.title}. {scene.summary}",
                }
            )
            continue
        for shot in shots:
            text = " ".join(
                part
                for part in (
                    scene.title,
                    scene.summary,
                    shot.action,
                    shot.dialogue_text,
                    shot.visual_composition,
                    shot.camera_movement,
                )
                if str(part or "").strip()
            )
            units.append(
                {
                    "scene_number": scene.scene_number,
                    "shot_numbers": [shot.shot_number],
                    "duration": int(shot.duration_seconds or 0),
                    "text": text,
                }
            )
    return units


def _segment_sources(
    script: Script,
    scenes: list[Scene],
    shots_by_scene: dict[UUID, list[Shot]],
    *,
    segment_duration_seconds: int,
) -> list[dict]:
    target_duration = max(
        int(script.target_duration_seconds or 0),
        sum(int(getattr(scene, "duration_seconds", 0) or 0) for scene in scenes),
        segment_duration_seconds,
    )
    segment_count = max(1, math.ceil(target_duration / segment_duration_seconds))
    shot_units = _ordered_shot_units(scenes, shots_by_scene)
    if not shot_units:
        chunks = _chunk_text_fallback(script.content, segment_count)
        return [
            {
                "text": chunk,
                "scene_numbers": [],
                "shot_numbers": [],
            }
            for chunk in chunks
        ]
    segments: list[dict] = []
    current: list[dict] = []
    current_duration = 0
    for unit in shot_units:
        unit_duration = max(1, int(unit["duration"] or segment_duration_seconds))
        if current and current_duration + unit_duration > segment_duration_seconds:
            segments.append(
                {
                    "text": " ".join(str(item["text"]) for item in current),
                    "scene_numbers": [item["scene_number"] for item in current],
                    "shot_numbers": [
                        shot_number
                        for item in current
                        for shot_number in item["shot_numbers"]
                    ],
                }
            )
            current = []
            current_duration = 0
        current.append(unit)
        current_duration += unit_duration
    if current:
        segments.append(
            {
                "text": " ".join(str(item["text"]) for item in current),
                "scene_numbers": [item["scene_number"] for item in current],
                "shot_numbers": [
                    shot_number for item in current for shot_number in item["shot_numbers"]
                ],
            }
        )
    return segments


def _visual_reference_text(visual_context: dict[str, list[dict[str, str]]]) -> str:
    lines: list[str] = []
    for label, key in (
        ("Personagens", "characters"),
        ("Locais", "locations"),
        ("Objetos", "props"),
    ):
        values = visual_context.get(key, [])
        if not values:
            continue
        joined = "; ".join(
            f"{item['name']}: {item.get('prompt') or item['name']}" for item in values[:4]
        )
        lines.append(f"{label}: {joined}.")
    return "\n".join(lines) or "Biblioteca Visual ainda sem itens aprovados."


def _segment_prompt(
    *,
    segment_number: int,
    source_text: str,
    visual_context: dict[str, list[dict[str, str]]],
    continuity: str,
) -> str:
    action = source_text.strip() or "acao visual principal do roteiro"
    return (
        f"Segmento {segment_number:02d} de video vertical 9:16, cinematografico e realista.\n"
        f"Acao principal: {action}.\n"
        f"Continuidade temporal: {continuity}.\n"
        "Preserve rigorosamente identidade, figurino, idade aparente, escala, luz, "
        "paleta e ambiente definidos na Biblioteca Visual.\n"
        f"{_visual_reference_text(visual_context)}\n"
        "Execute uma acao principal clara, natural e filmavel, sem reiniciar a cena. "
        f"{CONTINUOUS_VIDEO_NEGATIVE_PROMPT}"
    )


def build_continuous_video_segment_payloads(
    *,
    project_id: UUID,
    script: Script,
    scenes: list[Scene],
    shots_by_scene: dict[UUID, list[Shot]],
    visual_context: dict[str, list[dict[str, str]]],
    segment_duration_seconds: int = CONTINUOUS_VIDEO_DEFAULT_SEGMENT_SECONDS,
    provider: str = CONTINUOUS_VIDEO_DEFAULT_PROVIDER,
    model: str = CONTINUOUS_VIDEO_FAST_MODEL,
) -> list[ContinuousVideoSegmentCreate]:
    script_fingerprint = hashlib.sha256(
        f"{script.id}:{script.updated_at}:{script.content}".encode()
    ).hexdigest()
    visual_fingerprint = continuous_video_visual_fingerprint(visual_context)
    sources = _segment_sources(
        script,
        scenes,
        shots_by_scene,
        segment_duration_seconds=segment_duration_seconds,
    )
    payloads: list[ContinuousVideoSegmentCreate] = []
    previous_segment_id: UUID | None = None
    previous_segment_fingerprint = ""
    for index, source in enumerate(sources, 1):
        source_text = str(source.get("text") or "").strip()
        continuity = (
            "comece estabelecendo o momento inicial da historia"
            if index == 1
            else "continue diretamente o movimento e o estado emocional do segmento anterior"
        )
        prompt = _segment_prompt(
            segment_number=index,
            source_text=source_text,
            visual_context=visual_context,
            continuity=continuity,
        )
        metadata = {
            "action": source_text,
            "characters": _names_present(source_text, visual_context.get("characters", [])),
            "locations": _names_present(source_text, visual_context.get("locations", [])),
            "props": _names_present(source_text, visual_context.get("props", [])),
            "continuity": continuity,
            "negative_prompt": CONTINUOUS_VIDEO_NEGATIVE_PROMPT,
            "source_text": source_text,
            "source_scene_numbers": source.get("scene_numbers", []),
            "source_shot_numbers": source.get("shot_numbers", []),
            "visual_context": visual_context,
            "script_fingerprint": script_fingerprint,
            "visual_fingerprint": visual_fingerprint,
            "previous_segment_fingerprint": previous_segment_fingerprint,
            "custom_prompt": False,
        }
        fingerprint = continuous_video_request_fingerprint(
            project_id=project_id,
            segment_number=index,
            prompt=prompt,
            duration_seconds=segment_duration_seconds,
            provider=provider,
            model=model,
            script_fingerprint=script_fingerprint,
            visual_fingerprint=visual_fingerprint,
            source_segment_id=previous_segment_id,
            metadata=metadata,
        )
        payloads.append(
            ContinuousVideoSegmentCreate(
                segment_number=index,
                title=f"Segmento {index:02d}",
                prompt=prompt,
                duration_seconds=segment_duration_seconds,
                provider=provider,
                model=model,
                source_segment_id=previous_segment_id,
                request_fingerprint=fingerprint,
                metadata_json=metadata,
            )
        )
        previous_segment_fingerprint = fingerprint
    return payloads


async def _latest_script(session: AsyncSession, project_id: UUID) -> Script | None:
    result = await session.execute(
        select(Script).where(Script.project_id == project_id).order_by(Script.updated_at.desc())
    )
    return result.scalars().first()


async def _project_scenes_and_shots(
    session: AsyncSession,
    project_id: UUID,
) -> tuple[list[Scene], dict[UUID, list[Shot]]]:
    scene_result = await session.execute(
        select(Scene).where(Scene.project_id == project_id).order_by(Scene.scene_number)
    )
    scenes = list(scene_result.scalars())
    if not scenes:
        return [], {}
    scene_ids = [scene.id for scene in scenes]
    shot_result = await session.execute(
        select(Shot).where(Shot.scene_id.in_(scene_ids)).order_by(Shot.shot_number)
    )
    shots_by_scene: dict[UUID, list[Shot]] = {scene.id: [] for scene in scenes}
    for shot in shot_result.scalars():
        shots_by_scene.setdefault(shot.scene_id, []).append(shot)
    return scenes, shots_by_scene


async def _project_visual_context(
    session: AsyncSession,
    project_id: UUID,
) -> dict[str, list[dict[str, str]]]:
    characters = list(
        (
            await session.execute(
                select(Character).where(Character.project_id == project_id).order_by(Character.name)
            )
        ).scalars()
    )
    locations = list(
        (
            await session.execute(
                select(Location).where(Location.project_id == project_id).order_by(Location.name)
            )
        ).scalars()
    )
    props = list(
        (
            await session.execute(
                select(Prop).where(Prop.project_id == project_id).order_by(Prop.name)
            )
        ).scalars()
    )
    return continuous_video_visual_context(characters, locations, props)


async def plan_continuous_video_segments(
    session: AsyncSession,
    project_id: UUID,
    *,
    segment_duration_seconds: int = CONTINUOUS_VIDEO_DEFAULT_SEGMENT_SECONDS,
    provider: str = CONTINUOUS_VIDEO_DEFAULT_PROVIDER,
    model: str = CONTINUOUS_VIDEO_FAST_MODEL,
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
    planned_segments: list[ContinuousVideoSegment] = []
    previous_segment: ContinuousVideoSegment | None = None
    for payload in payloads:
        if previous_segment is not None:
            payload.source_segment_id = previous_segment.id
            payload.metadata_json = {
                **payload.metadata_json,
                "source_segment_id": str(previous_segment.id),
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
            existing.prompt = payload.prompt.strip()
            existing.duration_seconds = payload.duration_seconds
            existing.provider = payload.provider
            existing.model = payload.model
            existing.source_segment_id = payload.source_segment_id
            existing.source_video_asset_id = payload.source_video_asset_id
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
            existing.cost_estimate = estimate_operation_cost(
                "text_to_video",
                Decimal(existing.duration_seconds),
                provider=existing.provider,
                model=existing.model,
            ).estimated
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


async def _continuous_video_provider_for_project(
    session: AsyncSession,
    project_id: UUID,
    provider_name: str,
    model: str | None,
) -> tuple[VideoProvider, str, str, str, str]:
    app_settings = get_settings()
    production_settings = await get_or_create_production_settings(session, project_id)
    requested_provider = str(provider_name or "auto").strip().casefold()
    resolved_provider = (
        effective_provider_for_channel(app_settings, "video")
        if requested_provider == "auto"
        else requested_provider
    )
    if resolved_provider != "google_ai":
        raise ValueError("Provider de video continuo nao suportado. Use Google AI.")
    resolved_model = str(model or app_settings.google_ai_video_fast_model).strip()
    if not resolved_model:
        resolved_model = CONTINUOUS_VIDEO_FAST_MODEL
    return (
        GoogleAIVideoProvider(),
        "google_ai",
        resolved_model,
        production_settings.aspect_ratio,
        normalize_video_resolution(production_settings.video_resolution),
    )


async def _active_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
) -> ContinuousVideoSegment | None:
    result = await session.execute(
        select(ContinuousVideoSegment)
        .where(
            ContinuousVideoSegment.project_id == project_id,
            ContinuousVideoSegment.status == GenerationJobStatus.RUNNING,
        )
        .order_by(ContinuousVideoSegment.segment_number)
    )
    for segment in result.scalars():
        if not continuous_video_segment_is_stale_running(segment):
            return segment
    return None


def _continuous_video_job_idempotency_key(segment: ContinuousVideoSegment) -> str:
    return f"continuous-video:{segment.idempotency_key}"


async def _continuous_video_generation_job(
    session: AsyncSession,
    segment: ContinuousVideoSegment,
    *,
    provider: str,
    model: str,
    operation: str,
    aspect_ratio: str,
    resolution: str,
    continuation_mode: str,
) -> GenerationJob:
    idempotency_key = _continuous_video_job_idempotency_key(segment)
    result = await session.execute(
        select(GenerationJob).where(GenerationJob.idempotency_key == idempotency_key)
    )
    job = result.scalars().first()
    if job is None:
        job = GenerationJob(
            project_id=segment.project_id,
            job_type=GenerationJobType.VIDEO,
            status=GenerationJobStatus.RUNNING,
            progress=5,
            attempts=1,
            max_attempts=3,
            provider=provider,
            model=model,
            idempotency_key=idempotency_key,
            request_payload={},
            response_payload={},
            cost_estimate=segment.cost_estimate,
            started_at=datetime.now(UTC),
        )
        session.add(job)
    else:
        job.status = GenerationJobStatus.RUNNING
        job.progress = 5
        job.attempts += 1
        job.error = None
        job.completed_at = None
        job.provider = provider
        job.model = model
        job.started_at = datetime.now(UTC)
    job.request_payload = {
        "step": "continuous_video",
        "segment_id": str(segment.id),
        "segment_number": segment.segment_number,
        "duration_seconds": segment.duration_seconds,
        "prompt": segment.prompt,
        "provider": provider,
        "model": model,
        "operation": operation,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "source_segment_id": str(segment.source_segment_id) if segment.source_segment_id else None,
        "source_video_asset_id": (
            str(segment.source_video_asset_id) if segment.source_video_asset_id else None
        ),
        "continuation_mode": continuation_mode,
        "request_fingerprint": segment.request_fingerprint,
    }
    await session.flush()
    segment.generation_job_id = job.id
    return job


async def _emit_continuous_video_segment_event(
    session: AsyncSession,
    *,
    segment: ContinuousVideoSegment,
    status: str,
    provider: str,
    model: str,
    message: str,
    job: GenerationJob | None = None,
    estimated_cost: Decimal | None = None,
    details: dict[str, Any] | None = None,
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
            job_id=job.id if job is not None else segment.generation_job_id,
            event_type="continuous_video_segment",
            status=status,
            provider=provider,
            model=model,
            operation="text_to_video",
            estimated_cost=estimated_cost,
            message=message,
            details=payload,
        ),
    )


def _is_transient_continuous_video_error(error: str) -> bool:
    normalized = error.casefold()
    return any(
        marker in normalized
        for marker in (
            "timeout",
            "network",
            "connection",
            "internal error",
            "api_error",
            "rate limit",
            "429",
            "500",
            "502",
            "503",
            "504",
        )
    )


async def _mark_continuous_video_segment_failed(
    session: AsyncSession,
    *,
    segment: ContinuousVideoSegment,
    job: GenerationJob | None,
    reason: str,
    provider: str,
    model: str,
) -> None:
    segment.status = GenerationJobStatus.FAILED
    metadata = dict(segment.metadata_json or {})
    metadata["error"] = reason
    metadata["failed_at"] = datetime.now(UTC).isoformat()
    segment.metadata_json = metadata
    if job is not None:
        job.status = GenerationJobStatus.FAILED
        job.progress = 100
        job.error = reason
        job.completed_at = datetime.now(UTC)
        job.response_payload = {
            **(job.response_payload or {}),
            "error": reason,
            "segment_id": str(segment.id),
        }
    logger.warning(
        "continuous_video_generation_failed project_id=%s segment_number=%s "
        "provider=%s model=%s reason=%s",
        segment.project_id,
        segment.segment_number,
        provider,
        model,
        reason,
    )
    await _emit_continuous_video_segment_event(
        session,
        segment=segment,
        job=job,
        status="failed",
        provider=provider,
        model=model,
        message=reason,
    )


async def _persist_continuous_video_segment_success(
    session: AsyncSession,
    *,
    segment: ContinuousVideoSegment,
    job: GenerationJob,
    result: VideoResult,
    resumed_external_operation: bool,
) -> Asset:
    asset = Asset(
        project_id=segment.project_id,
        artifact_id=None,
        kind=AssetKind.VIDEO,
        name=f"Continuous segment {segment.segment_number:03d}",
        storage_uri=result.storage_uri or "",
        content_type=result.content_type,
        sha256=result.sha256,
        metadata_json={
            **result.metadata,
            "segment_id": str(segment.id),
            "segment_number": segment.segment_number,
            "request_fingerprint": segment.request_fingerprint,
        },
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
            metadata_json=asset.metadata_json,
        )
    )
    estimate = estimate_operation_cost(
        "text_to_video",
        Decimal(segment.duration_seconds),
        provider=result.provider,
        model=result.model,
    )
    provider_cost = Decimal(str(result.estimated_cost or "0.000000"))
    total_cost = final_budget_cost(estimate.estimated, provider_cost)
    segment.asset_id = asset.id
    segment.external_operation_id = result.external_job_id
    segment.provider = result.provider
    segment.model = result.model
    segment.status = GenerationJobStatus.SUCCEEDED
    segment.cost_estimate = total_cost
    metadata = dict(segment.metadata_json or {})
    metadata["asset_id"] = str(asset.id)
    metadata["external_operation_id"] = result.external_job_id
    metadata["completed_at"] = datetime.now(UTC).isoformat()
    metadata["resumed_external_operation"] = resumed_external_operation
    segment.metadata_json = metadata
    job.status = GenerationJobStatus.SUCCEEDED
    job.progress = 100
    job.external_job_id = result.external_job_id
    job.response_payload = result.metadata
    job.cost_estimate = total_cost
    job.completed_at = datetime.now(UTC)
    session.add(
        CostEntry(
            project_id=segment.project_id,
            artifact_id=None,
            entry_type=CostEntryType.ESTIMATE,
            provider=result.provider,
            model=result.model,
            operation="text_to_video",
            quantity=Decimal(segment.duration_seconds),
            unit="second",
            unit_cost=estimate.unit_cost,
            total_cost=total_cost,
            currency="USD",
            metadata_json=cost_audit_metadata(
                estimated_cost=estimate.estimated,
                provider_reported_cost=provider_cost,
                final_budget_cost=total_cost,
                stage="continuous_video",
                extra={
                    "job_id": str(job.id),
                    "segment_id": str(segment.id),
                    "segment_number": segment.segment_number,
                    "external_job_id": result.external_job_id,
                    "resumed_external_operation": resumed_external_operation,
                },
            ),
        )
    )
    await _emit_continuous_video_segment_event(
        session,
        segment=segment,
        job=job,
        status="succeeded",
        provider=result.provider,
        model=result.model,
        message="Segmento de video continuo concluido",
        estimated_cost=total_cost,
        details={
            "asset_id": str(asset.id),
            "external_job_id": result.external_job_id,
            "resumed_external_operation": resumed_external_operation,
        },
    )
    await session.flush()
    return asset


async def _run_continuous_video_provider_request(
    provider: VideoProvider,
    request: VideoRequest,
    *,
    external_operation_id: str | None = None,
    previous_video_uri: str | None = None,
) -> tuple[VideoResult | None, str | None, str | None]:
    resumed_operation = external_operation_id
    if external_operation_id:
        poller = getattr(provider, "poll_submitted", None)
        if not callable(poller):
            return None, None, "Provider nao permite retomar operacao de video."
        try:
            return await poller(request, external_operation_id), resumed_operation, None
        except Exception as exc:
            return None, resumed_operation, str(exc)
    if previous_video_uri:
        extension_generator = getattr(provider, "generate_extension", None)
        if callable(extension_generator):
            try:
                return await extension_generator(request, previous_video_uri), None, None
            except Exception as exc:
                return None, None, str(exc)
        extension_submitter = getattr(provider, "submit_extension", None)
        extension_poller = getattr(provider, "poll_submitted", None)
        if callable(extension_submitter) and callable(extension_poller):
            try:
                operation_id = await extension_submitter(request, previous_video_uri)
                result = await extension_poller(request, operation_id)
            except Exception as exc:
                return None, None, str(exc)
            return result, operation_id, None
        return (
            None,
            None,
            "Provider nao permite estender video anterior para continuidade temporal.",
        )
    submitter = getattr(provider, "submit_from_text", None)
    poller = getattr(provider, "poll_submitted", None)
    if callable(submitter) and callable(poller):
        for attempt in range(1, 3):
            try:
                operation_id = await submitter(request)
                result = await poller(request, operation_id)
            except Exception as exc:
                error = str(exc)
                if attempt == 2 or not _is_transient_continuous_video_error(error):
                    return None, None, error
                await asyncio.sleep(
                    exponential_backoff_seconds(attempt, base_seconds=1, cap_seconds=8)
                )
                continue
            return result, operation_id, None
    try:
        return await provider.generate_from_text(request), None, None
    except Exception as exc:
        return None, None, str(exc)


async def _continuous_video_assets_by_id(
    session: AsyncSession,
    asset_ids: set[UUID],
) -> dict[UUID, Asset]:
    if not asset_ids:
        return {}
    result = await session.execute(select(Asset).where(Asset.id.in_(asset_ids)))
    return {asset.id: asset for asset in result.scalars()}


def _continuous_video_progress_rows(
    segments: list[ContinuousVideoSegment],
    *,
    preexisting_succeeded_ids: set[UUID],
    active_segment_id: UUID | None = None,
    active_state: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment in segments:
        status = str(getattr(segment.status, "value", segment.status)).lower()
        if segment.id == active_segment_id and active_state:
            state = active_state
        elif status == "succeeded" and segment.id in preexisting_succeeded_ids:
            state = "skipped"
        elif status == "succeeded":
            state = "done"
        elif status == "failed":
            state = "failed"
        elif status == "running":
            state = "processing"
        else:
            state = "pending"
        rows.append(
            {
                "segment_id": str(segment.id),
                "segment_number": segment.segment_number,
                "title": segment.title or f"Segmento {segment.segment_number:02d}",
                "state": state,
                "duration_seconds": segment.duration_seconds,
                "cost_estimate": str(segment.cost_estimate or Decimal("0")),
                "error": (
                    (segment.metadata_json or {}).get("error")
                    if isinstance(segment.metadata_json, dict)
                    else None
                ),
            }
        )
    return rows


def _continuous_video_remaining_cost(segments: list[ContinuousVideoSegment]) -> Decimal:
    return sum(
        (
            Decimal(str(segment.cost_estimate or "0"))
            for segment in segments
            if segment.status
            not in {
                GenerationJobStatus.SUCCEEDED,
                GenerationJobStatus.CANCELLED,
            }
        ),
        Decimal("0.000000"),
    )


async def _publish_continuous_video_progress(
    callback: ContinuousVideoProgressCallback | None,
    segments: list[ContinuousVideoSegment],
    *,
    preexisting_succeeded_ids: set[UUID],
    active_segment_id: UUID | None = None,
    active_state: str | None = None,
) -> None:
    if callback is None:
        return
    result = callback(
        _continuous_video_progress_rows(
            segments,
            preexisting_succeeded_ids=preexisting_succeeded_ids,
            active_segment_id=active_segment_id,
            active_state=active_state,
        ),
        _continuous_video_remaining_cost(segments),
    )
    if isawaitable(result):
        await result


async def generate_continuous_video_segments(
    session: AsyncSession,
    project_id: UUID,
    *,
    segment_ids: list[UUID] | None = None,
    provider_name: str = "auto",
    model: str | None = None,
    retry_failed: bool = False,
    max_segments: int | None = None,
    pause_after_current: Callable[[], bool] | None = None,
    progress_callback: ContinuousVideoProgressCallback | None = None,
) -> tuple[list[GenerationJob], list[ContinuousVideoSegment]]:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        raise ValueError("Projeto nao encontrado.")
    active_segment = await _active_continuous_video_segment(session, project_id)
    if active_segment is not None:
        raise RuntimeError(
            f"Segmento {active_segment.segment_number} ja esta em geracao. "
            "Aguarde finalizar ou retome depois."
        )
    segments = await list_continuous_video_segments(session, project_id)
    if not segments:
        _plan, segments, validation_errors = await plan_continuous_video_segments(
            session,
            project_id,
            replace_existing=False,
        )
        if validation_errors:
            first_segment_number = min(validation_errors)
            raise ValueError(
                "Revise o planejamento antes de gerar: "
                + "; ".join(validation_errors[first_segment_number])
            )
    selected_ids = set(segment_ids or [])
    if selected_ids:
        segments = [segment for segment in segments if segment.id in selected_ids]
    if not segments:
        return [], []
    preexisting_succeeded_ids = {
        segment.id for segment in segments if segment.status == GenerationJobStatus.SUCCEEDED
    }
    provider, resolved_provider, resolved_model, aspect_ratio, resolution = (
        await _continuous_video_provider_for_project(session, project_id, provider_name, model)
    )
    billable_segments = [
        segment
        for segment in segments
        if continuous_video_segment_needs_generation(segment, retry_failed=retry_failed)
        and not segment.external_operation_id
        and segment.status != GenerationJobStatus.SUCCEEDED
    ]
    if max_segments is not None:
        billable_segments = billable_segments[: max(0, max_segments)]
    billable_seconds = sum(
        int(segment.duration_seconds or 0) for segment in billable_segments
    )
    estimate = estimate_operation_cost(
        "text_to_video",
        Decimal(billable_seconds),
        provider=resolved_provider,
        model=resolved_model,
    )
    await assert_project_budget_allows(
        session,
        project_id,
        estimate.estimated,
        stage="continuous_video",
    )
    video_dir = get_settings().local_storage_path / "google_ai_continuous_videos" / str(project_id)
    jobs: list[GenerationJob] = []
    processed: list[ContinuousVideoSegment] = []
    attempted_segments = 0
    previous_segment: ContinuousVideoSegment | None = None
    existing_asset_ids = {
        segment.asset_id for segment in await list_continuous_video_segments(session, project_id)
        if segment.asset_id is not None
    }
    assets_by_id = await _continuous_video_assets_by_id(session, existing_asset_ids)
    provider_supports_extension = bool(
        getattr(getattr(provider, "capabilities", None), "video_extension", False)
    )
    await _publish_continuous_video_progress(
        progress_callback,
        segments,
        preexisting_succeeded_ids=preexisting_succeeded_ids,
    )
    for segment in segments:
        if max_segments is not None and attempted_segments >= max(0, max_segments):
            break
        all_project_segments = await list_continuous_video_segments(session, project_id)
        previous_by_number = {
            item.segment_number: item for item in all_project_segments
        }.get(segment.segment_number - 1)
        if segment.segment_number > 1 and previous_by_number is not None:
            if previous_by_number.status != GenerationJobStatus.SUCCEEDED:
                message = (
                    f"Segmento {segment.segment_number} depende do segmento "
                    f"{previous_by_number.segment_number} concluido."
                )
                await _mark_continuous_video_segment_failed(
                    session,
                    segment=segment,
                    job=None,
                    reason=message,
                    provider=resolved_provider,
                    model=resolved_model,
                )
                await session.commit()
                processed.append(segment)
                break
            segment.source_segment_id = previous_by_number.id
            segment.source_video_asset_id = previous_by_number.asset_id
            previous_segment = previous_by_number
        elif segment.segment_number > 1 and previous_segment is None:
            raise ValueError(
                f"Segmento {segment.segment_number} nao possui segmento anterior planejado."
            )
        if segment.status == GenerationJobStatus.SUCCEEDED:
            processed.append(segment)
            continue
        if not continuous_video_segment_needs_generation(segment, retry_failed=retry_failed):
            processed.append(segment)
            continue
        attempted_segments += 1
        validation_errors = continuous_video_segment_validation_errors(segment)
        previous_asset = (
            assets_by_id.get(segment.source_video_asset_id)
            if segment.source_video_asset_id is not None
            else None
        )
        previous_video_uri = (
            str(previous_asset.storage_uri or "").strip() if previous_asset is not None else ""
        )
        continuation_mode = (
            "video_extension"
            if previous_video_uri and provider_supports_extension
            else "prompt_continuity"
        )
        job = await _continuous_video_generation_job(
            session,
            segment,
            provider=resolved_provider,
            model=resolved_model,
            operation="text_to_video",
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            continuation_mode=continuation_mode,
        )
        job.request_payload = {
            **(job.request_payload or {}),
            "source_video_uri": previous_video_uri or None,
        }
        jobs.append(job)
        if validation_errors:
            await _mark_continuous_video_segment_failed(
                session,
                segment=segment,
                job=job,
                reason="; ".join(validation_errors),
                provider=resolved_provider,
                model=resolved_model,
            )
            await session.commit()
            processed.append(segment)
            await _publish_continuous_video_progress(
                progress_callback,
                segments,
                preexisting_succeeded_ids=preexisting_succeeded_ids,
                active_segment_id=segment.id,
                active_state="failed",
            )
            break
        segment.status = GenerationJobStatus.RUNNING
        segment.provider = resolved_provider
        segment.model = resolved_model
        metadata = dict(segment.metadata_json or {})
        metadata["continuation_mode"] = continuation_mode
        metadata["started_at"] = datetime.now(UTC).isoformat()
        segment.metadata_json = metadata
        await _publish_continuous_video_progress(
            progress_callback,
            segments,
            preexisting_succeeded_ids=preexisting_succeeded_ids,
            active_segment_id=segment.id,
            active_state="sending",
        )
        await _emit_continuous_video_segment_event(
            session,
            segment=segment,
            job=job,
            status="started",
            provider=resolved_provider,
            model=resolved_model,
            message="Segmento de video continuo iniciado",
            estimated_cost=estimate.estimated,
            details={"continuation_mode": continuation_mode},
        )
        await session.commit()
        request = VideoRequest(
            prompt=segment.prompt,
            duration_seconds=segment.duration_seconds,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            size=resolution,
            output_dir=video_dir,
            model=resolved_model,
        )
        resumed_external_operation = bool(segment.external_operation_id)
        result, operation_id, error = await _run_continuous_video_provider_request(
            provider,
            request,
            external_operation_id=segment.external_operation_id,
            previous_video_uri=(
                previous_video_uri if continuation_mode == "video_extension" else None
            ),
        )
        if operation_id:
            segment.external_operation_id = operation_id
            job.external_job_id = operation_id
            job.progress = max(job.progress, 25)
            job.response_payload = {
                **(job.response_payload or {}),
                "external_operation_id": operation_id,
            }
            await _emit_continuous_video_segment_event(
                session,
                segment=segment,
                job=job,
                status="submitted",
                provider=resolved_provider,
                model=resolved_model,
                message="Segmento enviado ao provider",
                details={
                    "external_operation_id": operation_id,
                    "resumed_external_operation": resumed_external_operation,
                },
            )
            await session.commit()
        await _publish_continuous_video_progress(
            progress_callback,
            segments,
            preexisting_succeeded_ids=preexisting_succeeded_ids,
            active_segment_id=segment.id,
            active_state="processing",
        )
        if error is not None or result is None:
            await _mark_continuous_video_segment_failed(
                session,
                segment=segment,
                job=job,
                reason=error or "Provider nao retornou video para o segmento.",
                provider=resolved_provider,
                model=resolved_model,
            )
            await session.commit()
            processed.append(segment)
            await _publish_continuous_video_progress(
                progress_callback,
                segments,
                preexisting_succeeded_ids=preexisting_succeeded_ids,
                active_segment_id=segment.id,
                active_state="failed",
            )
            break
        job.progress = 90
        asset = await _persist_continuous_video_segment_success(
            session,
            segment=segment,
            job=job,
            result=result,
            resumed_external_operation=resumed_external_operation,
        )
        assets_by_id[asset.id] = asset
        processed.append(segment)
        await session.commit()
        await _publish_continuous_video_progress(
            progress_callback,
            segments,
            preexisting_succeeded_ids=preexisting_succeeded_ids,
            active_segment_id=segment.id,
            active_state="done",
        )
        if pause_after_current is not None and pause_after_current():
            break
    all_segments = await list_continuous_video_segments(session, project_id)
    if all_segments and all(
        segment.status == GenerationJobStatus.SUCCEEDED for segment in all_segments
    ):
        plan = await get_or_create_continuous_video_plan(session, project_id)
        plan.status = "completed"
        advance_project_status(project, ProjectStatus.VIDEO_REVIEW)
    elif processed:
        plan = await get_or_create_continuous_video_plan(session, project_id)
        plan.status = "generating"
        advance_project_status(project, ProjectStatus.VIDEO_GENERATION)
    await session.commit()
    for item in [*jobs, *processed]:
        await session.refresh(item)
    return jobs, processed


async def update_continuous_video_segment_prompt(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    prompt: str,
    title: str | None = None,
) -> ContinuousVideoSegment | None:
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    if segment.status == GenerationJobStatus.SUCCEEDED:
        raise ValueError("Segmento ja concluido nao pode ter prompt editado.")
    clean_prompt = prompt.strip()
    if len(clean_prompt.split()) < 20:
        raise ValueError("Prompt do segmento esta generico demais.")
    segment.prompt = clean_prompt
    if title is not None:
        segment.title = title.strip()
    metadata = dict(segment.metadata_json or {})
    metadata["custom_prompt"] = True
    segment.metadata_json = metadata
    segment.request_fingerprint = continuous_video_request_fingerprint(
        project_id=project_id,
        segment_number=segment.segment_number,
        prompt=segment.prompt,
        duration_seconds=segment.duration_seconds,
        provider=segment.provider,
        model=segment.model,
        source_segment_id=segment.source_segment_id,
        source_video_asset_id=segment.source_video_asset_id,
        metadata=metadata,
    )
    segment.idempotency_key = continuous_video_segment_idempotency_key(
        project_id,
        segment.segment_number,
        segment.provider,
        segment.model,
        segment.request_fingerprint,
    )
    await session.flush()
    return segment


async def attach_continuous_video_segment_result(
    session: AsyncSession,
    segment: ContinuousVideoSegment,
    *,
    asset_id: UUID,
    generation_job_id: UUID | None = None,
    external_operation_id: str | None = None,
) -> ContinuousVideoSegment:
    segment.asset_id = asset_id
    if generation_job_id is not None:
        segment.generation_job_id = generation_job_id
    if external_operation_id is not None:
        segment.external_operation_id = external_operation_id
    segment.status = GenerationJobStatus.SUCCEEDED
    await session.flush()
    return segment
