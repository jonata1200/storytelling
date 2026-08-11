import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import GenerationJobStatus
from app.costs.service import estimate_operation_cost
from app.projects.repository import ProjectRepository
from app.storytelling.models import Scene, Script, Shot
from app.video_generation.models import ContinuousVideoPlan, ContinuousVideoSegment
from app.video_generation.schemas import (
    ContinuousVideoPlanCreate,
    ContinuousVideoSegmentCreate,
)
from app.visual_bible.models import Character, Location, Prop

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
                "image_to_video",
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
