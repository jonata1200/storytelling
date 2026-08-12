import asyncio
import hashlib
import json
import logging
import math
import mimetypes
import re
import subprocess
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from inspect import isawaitable
from pathlib import Path
from typing import Any, cast
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
from app.providers.media_utils import resolve_ffmpeg_path
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
from app.visual_bible.models import Character, Location, Prop, VisualReference
from app.workflows.state_machine import advance_project_status

logger = logging.getLogger(__name__)
ContinuousVideoProgressCallback = Callable[
    [list[dict[str, Any]], Decimal],
    Awaitable[None] | None,
]

CONTINUOUS_VIDEO_DEFAULT_PROVIDER = "google_ai"
CONTINUOUS_VIDEO_DEFAULT_MODEL = "veo-3.1-generate-preview"
CONTINUOUS_VIDEO_FAST_MODEL = "veo-3.1-fast-generate-preview"
CONTINUOUS_VIDEO_DEFAULT_SEGMENT_SECONDS = 8
CONTINUOUS_VIDEO_REFERENCE_LIMIT = 3
CONTINUOUS_VIDEO_MIN_APPROVED_SEGMENTS = 3
CONTINUOUS_VIDEO_REVIEW_PENDING = "pending"
CONTINUOUS_VIDEO_REVIEW_GENERATING = "generating"
CONTINUOUS_VIDEO_REVIEW_READY = "ready_for_review"
CONTINUOUS_VIDEO_REVIEW_APPROVED = "approved"
CONTINUOUS_VIDEO_REVIEW_REJECTED = "rejected"
CONTINUOUS_VIDEO_REVIEW_FAILED = "failed"
CONTINUOUS_VIDEO_REVIEW_STATUSES = {
    CONTINUOUS_VIDEO_REVIEW_PENDING,
    CONTINUOUS_VIDEO_REVIEW_GENERATING,
    CONTINUOUS_VIDEO_REVIEW_READY,
    CONTINUOUS_VIDEO_REVIEW_APPROVED,
    CONTINUOUS_VIDEO_REVIEW_REJECTED,
    CONTINUOUS_VIDEO_REVIEW_FAILED,
}
CONTINUOUS_VIDEO_NEGATIVE_PROMPT = (
    "Nao criar legendas, marcas d'agua, logos, texto na imagem, troca de identidade, "
    "mudanca brusca de figurino, mudanca de local sem acao visivel, cortes abruptos, "
    "flicker, morphing ou deformacao de rosto, maos e objetos."
)
_FRAGILE_SEGMENT_END_WORDS = {
    "a",
    "as",
    "com",
    "como",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "mas",
    "o",
    "os",
    "ou",
    "para",
    "por",
    "que",
    "sem",
    "the",
    "of",
    "and",
    "or",
    "but",
    "with",
    "without",
    "to",
    "for",
    "from",
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


def continuous_video_segment_is_approved(segment: ContinuousVideoSegment | None) -> bool:
    if segment is None:
        return False
    return (
        segment.status == GenerationJobStatus.SUCCEEDED
        and normalize_continuous_video_review_status(getattr(segment, "review_status", None))
        == CONTINUOUS_VIDEO_REVIEW_APPROVED
    )


def continuous_video_request_fingerprint(
    *,
    project_id: UUID,
    segment_number: int,
    prompt: str,
    duration_seconds: int,
    provider: str = CONTINUOUS_VIDEO_DEFAULT_PROVIDER,
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


def _last_word(text: str) -> str:
    words = re.findall(r"[^\W\d_]+", text.casefold())
    return words[-1] if words else ""


def _segment_action_has_fragile_ending(text: str) -> bool:
    return _last_word(text) in _FRAGILE_SEGMENT_END_WORDS


def _prompt_has_fragile_sentence(prompt: str) -> bool:
    for sentence in re.findall(r"[^.!?\n]{10,}[.!?]", prompt):
        if _segment_action_has_fragile_ending(sentence):
            return True
    return False


def _normalize_segment_action(source_text: str) -> str:
    action = re.sub(r"\s+", " ", str(source_text or "")).strip()
    if not action:
        action = "acao visual principal do roteiro"
    if action.endswith((".", "!", "?")):
        return action
    return f"{action}."


def _segment_action_guidance(action: str) -> str:
    normalized = action.casefold()
    if any(term in normalized for term in _ABSTRACT_SEGMENT_TERMS):
        return (
            "Converta ideias internas em sinais visiveis: postura, olhar, respiracao, "
            "gesto de maos e interacao com objetos."
        )
    return (
        "Mostre a acao em comportamento fisico claro, sem narracao escrita ou texto na tela."
    )


def continuous_video_segment_validation_errors(segment: ContinuousVideoSegment) -> list[str]:
    errors: list[str] = []
    prompt = str(segment.prompt or "").strip()
    metadata = segment.metadata_json if isinstance(segment.metadata_json, dict) else {}
    action = str(metadata.get("action") or "").strip()
    if segment.segment_number <= 0:
        errors.append("numero de segmento invalido")
    if segment.duration_seconds <= 0:
        errors.append("duracao invalida")
    if len(prompt.split()) < 20:
        errors.append("prompt generico demais")
    if not action:
        errors.append("acao principal ausente")
    elif _segment_action_has_fragile_ending(action):
        errors.append("acao principal termina em frase incompleta")
    if _prompt_has_fragile_sentence(prompt):
        errors.append("prompt contem frase incompleta")
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
    paragraphs = _script_visual_paragraphs(content)
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
    action_units = _script_action_units_for_chunks(paragraphs)
    if not action_units:
        return ["acao visual principal do roteiro"] * segment_count
    total_words = sum(len(unit.split()) for unit in action_units)
    target_words = max(1, math.ceil(total_words / segment_count))
    chunks: list[str] = []
    current_units: list[str] = []
    current_words = 0
    for unit in action_units:
        if current_units and current_words >= target_words and len(chunks) < segment_count - 1:
            chunks.append(" ".join(current_units).strip())
            current_units = []
            current_words = 0
        current_units.append(unit)
        current_words += len(unit.split())
    if current_units:
        chunks.append(" ".join(current_units).strip())
    while len(chunks) < segment_count:
        chunks.append(chunks[-1])
    return chunks[:segment_count]


def _script_visual_paragraphs(content: str) -> list[str]:
    raw_paragraphs = [part.strip() for part in content.splitlines() if part.strip()]
    paragraphs: list[str] = []
    pending_headers: list[str] = []
    for paragraph in raw_paragraphs:
        if _is_transition_marker(paragraph):
            continue
        if _is_scene_marker(paragraph) or _is_slugline(paragraph):
            pending_headers.append(paragraph)
            continue
        if pending_headers:
            paragraphs.append("\n".join([*pending_headers, paragraph]))
            pending_headers = []
            continue
        paragraphs.append(paragraph)
    return paragraphs


def _script_action_text_for_chunks(paragraphs: list[str]) -> str:
    return " ".join(_script_action_units_for_chunks(paragraphs))


def _script_action_units_for_chunks(paragraphs: list[str]) -> list[str]:
    action_lines: list[str] = []
    for paragraph in paragraphs:
        for line in paragraph.splitlines():
            clean_line = line.strip()
            if not clean_line:
                continue
            if _is_transition_marker(clean_line) or _is_scene_marker(clean_line) or _is_slugline(
                clean_line
            ):
                continue
            action_lines.append(clean_line)
    action_text = " ".join(action_lines)
    units = [unit.strip() for unit in re.split(r"(?<=[.!?])\s+", action_text) if unit.strip()]
    return units or ([action_text.strip()] if action_text.strip() else [])


def _is_transition_marker(text: str) -> bool:
    normalized = text.strip().casefold().rstrip(":.")
    return normalized in {"fade in", "fade out", "corta para", "cut to"}


def _is_scene_marker(text: str) -> bool:
    return re.match(r"(?i)^cena\s+\d+\b", text.strip()) is not None


def _is_slugline(text: str) -> bool:
    normalized = text.strip().casefold()
    return normalized.startswith(("int.", "ext.", "int/ext.", "int./ext."))


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


def _compact_visual_prompt(value: object, max_chars: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,.;") + "."


def _visual_reference_text(
    visual_context: dict[str, list[dict[str, str]]],
    *,
    source_text: str = "",
) -> str:
    lines: list[str] = []
    for label, key in (
        ("Personagens", "characters"),
        ("Locais", "locations"),
        ("Objetos", "props"),
    ):
        values = visual_context.get(key, [])
        if not values:
            continue
        names = set(_names_present(source_text, values)) if source_text else set()
        selected = [item for item in values if item.get("name") in names] or values[:2]
        joined = "; ".join(
            f"{item['name']}: {_compact_visual_prompt(item.get('prompt') or item['name'])}"
            for item in selected[:2]
        )
        lines.append(f"{label}: {joined}.")
    if not lines:
        return "Biblioteca Visual ainda sem itens aprovados."
    return (
        "\n".join(lines)
        + "\nUse as imagens de referencia anexadas como fonte principal de identidade visual."
    )


def _segment_prompt(
    *,
    segment_number: int,
    source_text: str,
    visual_context: dict[str, list[dict[str, str]]],
    continuity: str,
    duration_seconds: int,
) -> str:
    action = _normalize_segment_action(source_text)
    continuity_sentence = _normalize_segment_action(continuity)
    action_guidance = _segment_action_guidance(action)
    return (
        f"Prompt Veo 3.1 - Segmento {segment_number:02d}\n\n"
        f"Plano unico vertical 9:16, live action realista, {int(duration_seconds)}s. "
        "Sem montagem, texto na tela ou salto temporal interno.\n\n"
        "Acao\n"
        f"{action}\n"
        f"{action_guidance}\n\n"
        "Continuidade\n"
        f"{continuity_sentence} Preserve identidade, idade aparente, figurino, "
        "posicao, movimento, emocao, escala, paleta, luz, ambiente e objetos. "
        "Se houver frame inicial, comece exatamente dele.\n\n"
        "Camera\n"
        "Composicao limpa para mobile, movimento suave, foco no sujeito e leitura "
        "clara dos objetos importantes.\n\n"
        "Biblioteca Visual\n"
        f"{_visual_reference_text(visual_context, source_text=source_text)}\n\n"
        "Negativo\n"
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
    model: str = CONTINUOUS_VIDEO_DEFAULT_MODEL,
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
        action = _normalize_segment_action(source_text)
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
            duration_seconds=segment_duration_seconds,
        )
        metadata = {
            "action": action,
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
                script_id=script.id,
                segment_number=index,
                title=f"Segmento {index:02d}",
                prompt=prompt,
                duration_seconds=segment_duration_seconds,
                provider=provider,
                model=model,
                review_status=CONTINUOUS_VIDEO_REVIEW_PENDING,
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
            existing.review_status = normalize_continuous_video_review_status(
                payload.review_status
            )
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
    resolved_model = str(model or app_settings.google_ai_video_model).strip()
    if not resolved_model:
        resolved_model = CONTINUOUS_VIDEO_DEFAULT_MODEL
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
    segment.review_status = CONTINUOUS_VIDEO_REVIEW_FAILED
    metadata = dict(segment.metadata_json or {})
    metadata["error"] = reason
    metadata["failed_at"] = datetime.now(UTC).isoformat()
    metadata["review_status"] = CONTINUOUS_VIDEO_REVIEW_FAILED
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
    segment.generated_video_asset_id = asset.id
    segment.external_operation_id = result.external_job_id
    segment.provider = result.provider
    segment.model = result.model
    segment.status = GenerationJobStatus.SUCCEEDED
    segment.cost_estimate = total_cost
    metadata = dict(segment.metadata_json or {})
    metadata["asset_id"] = str(asset.id)
    metadata["generated_video_asset_id"] = str(asset.id)
    metadata["external_operation_id"] = result.external_job_id
    metadata["completed_at"] = datetime.now(UTC).isoformat()
    metadata["resumed_external_operation"] = resumed_external_operation
    segment.metadata_json = metadata
    await _extract_and_persist_continuous_video_frames(
        session,
        segment=segment,
        video_asset=asset,
        force=True,
    )
    _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_READY)
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
    if request.source_image_uri:
        submitter = getattr(provider, "submit_from_image", None)
        poller = getattr(provider, "poll_submitted_from_image", None) or getattr(
            provider,
            "poll_submitted",
            None,
        )
        if callable(submitter) and callable(poller):
            try:
                operation_id = await submitter(request)
                result = await poller(request, operation_id)
            except Exception as exc:
                return None, None, str(exc)
            return result, operation_id, None
        try:
            return await provider.generate_from_image(request), None, None
        except Exception as exc:
            return None, None, str(exc)
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


def _continuous_video_reference_view_priority(target_kind: str, view_type: str) -> int:
    priorities = {
        "character": {"front_portrait": 0, "character_reference_sheet": 1},
        "location": {"establishing": 0},
        "prop": {"front": 0, "side": 1, "prop_reference_sheet": 2},
    }
    return priorities.get(target_kind, {}).get(view_type, 99)


def _continuous_video_reference_match_text(segment: ContinuousVideoSegment) -> str:
    metadata = segment.metadata_json if isinstance(segment.metadata_json, dict) else {}
    return " ".join(
        str(value or "")
        for value in (
            metadata.get("source_text"),
            metadata.get("action"),
            segment.prompt,
        )
    ).casefold()


async def _continuous_video_reference_uris_for_segment(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    *,
    limit: int = CONTINUOUS_VIDEO_REFERENCE_LIMIT,
) -> list[str]:
    if limit <= 0 or not hasattr(session, "execute"):
        return []
    normalized_text = _continuous_video_reference_match_text(segment)
    target_rows: list[tuple[str, UUID, str, int]] = []
    for target_kind, model, kind_priority in (
        ("character", Character, 0),
        ("location", Location, 1),
        ("prop", Prop, 2),
    ):
        result = await session.execute(
            select(model).where(model.project_id == project_id).order_by(model.created_at)
        )
        for item in result.scalars():
            item = cast(Character | Location | Prop, item)
            name = str(getattr(item, "name", "") or "").strip()
            score = 20 if name and name.casefold() in normalized_text else 0
            target_rows.append((target_kind, item.id, name, score - kind_priority))
    if not target_rows:
        return []

    target_ids_by_kind: dict[str, list[UUID]] = {}
    for target_kind, target_id, _name, _score in target_rows:
        target_ids_by_kind.setdefault(target_kind, []).append(target_id)

    references_by_target: dict[tuple[str, UUID], list[VisualReference]] = {}
    for target_kind, target_ids in target_ids_by_kind.items():
        refs_result = await session.execute(
            select(VisualReference)
            .where(
                VisualReference.project_id == project_id,
                VisualReference.target_kind == target_kind,
                VisualReference.target_id.in_(target_ids),
                VisualReference.asset_id.is_not(None),
            )
            .order_by(VisualReference.created_at.desc())
        )
        for reference in refs_result.scalars():
            key = (reference.target_kind, reference.target_id)
            references_by_target.setdefault(key, []).append(reference)

    selected_targets = sorted(target_rows, key=lambda row: (-row[3], row[0], row[2]))[:limit]
    reference_uris: list[str] = []
    seen: set[str] = set()
    for target_kind, target_id, _name, _score in selected_targets:
        references = sorted(
            references_by_target.get((target_kind, target_id), []),
            key=lambda item: (
                _continuous_video_reference_view_priority(item.target_kind, item.view_type),
                -item.created_at.timestamp(),
            ),
        )
        if not references:
            continue
        asset = await session.get(Asset, references[0].asset_id)
        storage_uri = str(getattr(asset, "storage_uri", "") or "").strip() if asset else ""
        if storage_uri and storage_uri not in seen:
            seen.add(storage_uri)
            reference_uris.append(storage_uri)
        if len(reference_uris) >= limit:
            break
    return reference_uris


def _continuous_video_model_for_reference_images(
    resolved_provider: str,
    resolved_model: str,
    reference_uris: list[str],
) -> str:
    if not reference_uris or resolved_provider != "google_ai":
        return resolved_model
    if GoogleAIVideoProvider._model_supports_reference_images(resolved_model):
        return resolved_model
    configured_model = str(getattr(get_settings(), "google_ai_video_model", "") or "").strip()
    if GoogleAIVideoProvider._model_supports_reference_images(configured_model):
        return configured_model
    return CONTINUOUS_VIDEO_DEFAULT_MODEL


def _continuous_video_local_storage_path(storage_uri: str) -> Path | None:
    if not storage_uri or storage_uri.startswith(("http://", "https://", "data:")):
        return None
    storage_root = get_settings().local_storage_path.resolve()
    candidate = Path(storage_uri)
    candidates = [candidate] if candidate.is_absolute() else [storage_root / candidate, candidate]
    for path in candidates:
        try:
            resolved = path.resolve(strict=False)
            resolved.relative_to(storage_root)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved.is_file():
            return resolved
    return None


def _continuous_video_ffmpeg_path() -> str | None:
    return resolve_ffmpeg_path(getattr(get_settings(), "ffmpeg_path", ""))


def _continuous_video_frame_extract_commands(
    ffmpeg_path: str,
    source_path: Path,
    output_path: Path,
    *,
    normalized_role: str,
) -> list[list[str]]:
    base_args = [
        ffmpeg_path,
        "-y",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
    ]
    if normalized_role == "initial":
        return [base_args]
    return [
        [
            ffmpeg_path,
            "-y",
            "-sseof",
            "-0.1",
            "-i",
            str(source_path),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ],
        [
            ffmpeg_path,
            "-y",
            "-sseof",
            "-1",
            "-i",
            str(source_path),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ],
        base_args,
    ]


def _extract_continuous_video_frame(
    video_asset: Asset,
    *,
    segment_number: int,
    frame_role: str,
) -> tuple[Path | None, str | None]:
    normalized_role = "initial" if frame_role == "initial" else "final"
    role_label = "inicial" if normalized_role == "initial" else "final"
    ffmpeg_path = _continuous_video_ffmpeg_path()
    if not ffmpeg_path:
        return None, f"FFmpeg nao encontrado para extrair frame {role_label}."
    source_path = _continuous_video_local_storage_path(str(video_asset.storage_uri or ""))
    if source_path is None:
        return None, "Arquivo de video nao encontrado no armazenamento local."
    output_dir = source_path.parent / "frames"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        output_dir / f"{source_path.stem}_segment_{segment_number:03d}_{normalized_role}.jpg"
    )
    command_errors: list[str] = []
    for command in _continuous_video_frame_extract_commands(
        ffmpeg_path,
        source_path,
        output_path,
        normalized_role=normalized_role,
    ):
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            command_errors.append(str(exc))
            continue
        if completed.returncode == 0 and output_path.is_file():
            return output_path, None
        detail = (completed.stderr or completed.stdout or "").strip()
        if detail:
            command_errors.append(detail[:500])
    if command_errors:
        return None, f"FFmpeg nao extraiu frame {role_label}: {command_errors[-1]}"
    if not output_path.is_file():
        return None, f"FFmpeg nao gerou arquivo para o frame {role_label}."
    return output_path, None


def _extract_continuous_video_initial_frame(
    video_asset: Asset,
    *,
    segment_number: int,
) -> tuple[Path | None, str | None]:
    return _extract_continuous_video_frame(
        video_asset,
        segment_number=segment_number,
        frame_role="initial",
    )


def _extract_continuous_video_final_frame(
    video_asset: Asset,
    *,
    segment_number: int,
) -> tuple[Path | None, str | None]:
    return _extract_continuous_video_frame(
        video_asset,
        segment_number=segment_number,
        frame_role="final",
    )


async def _persist_continuous_video_frame_asset(
    session: AsyncSession,
    *,
    segment: ContinuousVideoSegment,
    video_asset: Asset,
    frame_path: Path,
    frame_role: str,
) -> Asset:
    normalized_role = "initial" if frame_role == "initial" else "final"
    role_label = "initial" if normalized_role == "initial" else "final"
    frame_bytes = await asyncio.to_thread(frame_path.read_bytes)
    content_type = mimetypes.guess_type(frame_path.name)[0] or "image/jpeg"
    asset = Asset(
        project_id=segment.project_id,
        artifact_id=None,
        kind=AssetKind.IMAGE,
        name=f"Continuous segment {segment.segment_number:03d} {role_label} frame",
        storage_uri=frame_path.as_posix(),
        content_type=content_type,
        sha256=hashlib.sha256(frame_bytes).hexdigest(),
        metadata_json={
            "segment_id": str(segment.id),
            "segment_number": segment.segment_number,
            "source_video_asset_id": str(video_asset.id),
            "technical_role": f"continuous_video_{role_label}_frame",
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
    if normalized_role == "final":
        segment.final_frame_asset_id = asset.id
    return asset


async def _persist_continuous_video_final_frame_asset(
    session: AsyncSession,
    *,
    segment: ContinuousVideoSegment,
    video_asset: Asset,
    frame_path: Path,
) -> Asset:
    return await _persist_continuous_video_frame_asset(
        session,
        segment=segment,
        video_asset=video_asset,
        frame_path=frame_path,
        frame_role="final",
    )


async def _extract_and_persist_continuous_video_frames(
    session: AsyncSession,
    *,
    segment: ContinuousVideoSegment,
    video_asset: Asset,
    force: bool = False,
) -> dict[str, str]:
    metadata = dict(segment.metadata_json or {})
    errors: dict[str, str] = {}
    for frame_role, extractor in (
        ("initial", _extract_continuous_video_initial_frame),
        ("final", _extract_continuous_video_final_frame),
    ):
        metadata.pop(f"{frame_role}_frame_error", None)
        existing_asset_id = (
            segment.final_frame_asset_id
            if frame_role == "final"
            else metadata.get("initial_frame_asset_id")
        )
        if existing_asset_id and not force:
            continue
        frame_path, frame_error = extractor(video_asset, segment_number=segment.segment_number)
        if frame_path is None:
            if frame_error:
                metadata[f"{frame_role}_frame_error"] = frame_error
                errors[frame_role] = frame_error
            continue
        frame_asset = await _persist_continuous_video_frame_asset(
            session,
            segment=segment,
            video_asset=video_asset,
            frame_path=frame_path,
            frame_role=frame_role,
        )
        metadata[f"{frame_role}_frame_asset_id"] = str(frame_asset.id)
        metadata[f"{frame_role}_frame_storage_uri"] = frame_asset.storage_uri
    segment.metadata_json = metadata
    await session.flush()
    return errors


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
    dependency_segments = {
        segment.segment_number: segment
        for segment in await list_continuous_video_segments(session, project_id)
    }
    billable_segments: list[ContinuousVideoSegment] = []
    for segment in segments:
        if (
            not continuous_video_segment_needs_generation(segment, retry_failed=retry_failed)
            or segment.external_operation_id
            or segment.status == GenerationJobStatus.SUCCEEDED
        ):
            continue
        previous_for_budget = dependency_segments.get(segment.segment_number - 1)
        if segment.segment_number > 1 and not continuous_video_segment_is_approved(
            previous_for_budget
        ):
            break
        billable_segments.append(segment)
        break
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
        asset_id
        for segment in await list_continuous_video_segments(session, project_id)
        for asset_id in (
            segment.asset_id,
            segment.generated_video_asset_id,
            segment.source_video_asset_id,
            segment.source_frame_asset_id,
            segment.final_frame_asset_id,
        )
        if asset_id is not None
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
            if not continuous_video_segment_is_approved(previous_by_number):
                break
            segment.source_segment_id = previous_by_number.id
            segment.source_video_asset_id = previous_by_number.asset_id
            segment.source_frame_asset_id = previous_by_number.final_frame_asset_id
            if previous_by_number.final_frame_asset_id is not None:
                previous_metadata = (
                    previous_by_number.metadata_json
                    if isinstance(previous_by_number.metadata_json, dict)
                    else {}
                )
                metadata = dict(segment.metadata_json or {})
                metadata["source_frame_asset_id"] = str(previous_by_number.final_frame_asset_id)
                if previous_metadata.get("final_frame_storage_uri"):
                    metadata["source_frame_storage_uri"] = previous_metadata[
                        "final_frame_storage_uri"
                    ]
                segment.metadata_json = metadata
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
        source_frame_asset = (
            assets_by_id.get(segment.source_frame_asset_id)
            if segment.source_frame_asset_id is not None
            else None
        )
        previous_video_uri = (
            str(previous_asset.storage_uri or "").strip() if previous_asset is not None else ""
        )
        source_frame_uri = (
            str(source_frame_asset.storage_uri or "").strip()
            if source_frame_asset is not None
            else str((segment.metadata_json or {}).get("source_frame_storage_uri") or "").strip()
        )
        continuation_mode = (
            "final_frame_i2v"
            if source_frame_uri and getattr(provider.capabilities, "image_to_video", False)
            else
            "video_extension"
            if previous_video_uri and provider_supports_extension
            else "prompt_continuity"
        )
        operation = "image_to_video" if continuation_mode == "final_frame_i2v" else "text_to_video"
        reference_limit = (
            int(getattr(provider.capabilities, "max_reference_images", 0) or 0)
            if getattr(provider.capabilities, "reference_images", False)
            else 0
        )
        reference_uris = await _continuous_video_reference_uris_for_segment(
            session,
            project_id,
            segment,
            limit=reference_limit,
        )
        request_model = _continuous_video_model_for_reference_images(
            resolved_provider,
            resolved_model,
            reference_uris,
        )
        if request_model != resolved_model:
            request_estimate = estimate_operation_cost(
                operation,
                Decimal(segment.duration_seconds),
                provider=resolved_provider,
                model=request_model,
            )
            await assert_project_budget_allows(
                session,
                project_id,
                request_estimate.estimated,
                stage="continuous_video",
            )
        job = await _continuous_video_generation_job(
            session,
            segment,
            provider=resolved_provider,
            model=request_model,
            operation=operation,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            continuation_mode=continuation_mode,
        )
        job.request_payload = {
            **(job.request_payload or {}),
            "source_video_uri": previous_video_uri or None,
            "source_frame_uri": source_frame_uri or None,
            "reference_uris": reference_uris,
            "reference_count": len(reference_uris),
        }
        jobs.append(job)
        if validation_errors:
            await _mark_continuous_video_segment_failed(
                session,
                segment=segment,
                job=job,
                reason="; ".join(validation_errors),
                provider=resolved_provider,
                model=request_model,
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
        _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_GENERATING)
        segment.provider = resolved_provider
        segment.model = request_model
        metadata = dict(segment.metadata_json or {})
        metadata["continuation_mode"] = continuation_mode
        metadata["reference_uris"] = reference_uris
        metadata["reference_count"] = len(reference_uris)
        if request_model != resolved_model:
            metadata["requested_model_before_reference_upgrade"] = resolved_model
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
            model=request_model,
            message="Segmento de video continuo iniciado",
            estimated_cost=estimate.estimated,
            details={
                "continuation_mode": continuation_mode,
                "reference_count": len(reference_uris),
            },
        )
        await session.commit()
        request = VideoRequest(
            prompt=segment.prompt,
            duration_seconds=segment.duration_seconds,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            size=resolution,
            source_image_uri=source_frame_uri or None,
            reference_uris=reference_uris,
            output_dir=video_dir,
            model=request_model,
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
                model=request_model,
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
                model=request_model,
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


async def approve_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    note: str | None = None,
) -> ContinuousVideoSegment | None:
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    if segment.status != GenerationJobStatus.SUCCEEDED or segment.asset_id is None:
        raise ValueError("Somente segmentos gerados podem ser aprovados.")
    previous_status = normalize_continuous_video_review_status(
        getattr(segment, "review_status", None)
    )
    _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_APPROVED, note=note)
    metadata = dict(segment.metadata_json or {})
    metadata["review_decision"] = CONTINUOUS_VIDEO_REVIEW_APPROVED
    metadata["review_decision_at"] = datetime.now(UTC).isoformat()
    metadata["review_previous_status"] = previous_status
    if note is not None:
        metadata["review_note"] = note
    metadata["continuity_summary"] = continuous_video_segment_continuity_summary(segment)
    segment.metadata_json = metadata
    next_segment = await get_continuous_video_segment_by_number(
        session,
        project_id,
        segment.segment_number + 1,
    )
    if next_segment is not None and not continuous_video_segment_is_approved(next_segment):
        next_segment.source_segment_id = segment.id
        next_segment.source_video_asset_id = segment.asset_id
        next_segment.source_frame_asset_id = segment.final_frame_asset_id
        next_metadata = dict(next_segment.metadata_json or {})
        next_metadata["source_segment_id"] = str(segment.id)
        next_metadata["source_video_asset_id"] = str(segment.asset_id)
        if segment.final_frame_asset_id is not None:
            next_metadata["source_frame_asset_id"] = str(segment.final_frame_asset_id)
        if metadata.get("final_frame_storage_uri"):
            next_metadata["source_frame_storage_uri"] = metadata["final_frame_storage_uri"]
        next_metadata["continuity_source_summary"] = metadata["continuity_summary"]
        next_segment.metadata_json = next_metadata
    await session.flush()
    return segment


def continuous_video_segment_continuity_summary(segment: ContinuousVideoSegment) -> str:
    metadata = segment.metadata_json if isinstance(segment.metadata_json, dict) else {}
    parts = [
        f"Segmento {int(getattr(segment, 'segment_number', 0) or 0):02d}",
        str(getattr(segment, "title", "") or "").strip(),
        str(metadata.get("action") or "").strip(),
        str(metadata.get("continuity") or "").strip(),
    ]
    names = [
        *list(metadata.get("characters") or []),
        *list(metadata.get("locations") or []),
        *list(metadata.get("props") or []),
    ]
    visual_anchor = ", ".join(str(name) for name in names if str(name).strip())
    if visual_anchor:
        parts.append(f"Referencias: {visual_anchor}")
    summary = " | ".join(part for part in parts if part)
    return summary[:800]


async def reject_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    note: str | None = None,
) -> ContinuousVideoSegment | None:
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    if segment.status != GenerationJobStatus.SUCCEEDED or segment.asset_id is None:
        raise ValueError("Somente segmentos gerados podem ser rejeitados.")
    previous_status = normalize_continuous_video_review_status(
        getattr(segment, "review_status", None)
    )
    _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_REJECTED, note=note)
    metadata = dict(segment.metadata_json or {})
    metadata["review_decision"] = CONTINUOUS_VIDEO_REVIEW_REJECTED
    metadata["review_decision_at"] = datetime.now(UTC).isoformat()
    metadata["review_previous_status"] = previous_status
    if note is not None:
        metadata["review_note"] = note
    segment.metadata_json = metadata
    await invalidate_continuous_video_downstream_segments(
        session,
        project_id,
        segment.segment_number,
        reason="upstream_rejected",
    )
    await session.flush()
    return segment


async def retry_failed_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    provider_name: str = "auto",
    model: str | None = None,
    progress_callback: ContinuousVideoProgressCallback | None = None,
) -> tuple[list[GenerationJob], list[ContinuousVideoSegment]]:
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return [], []
    if segment.status != GenerationJobStatus.FAILED:
        raise ValueError("Somente segmentos com falha podem ser reenviados.")
    return await generate_continuous_video_segment(
        session,
        project_id,
        segment_id,
        provider_name=provider_name,
        model=model,
        retry_failed=True,
        progress_callback=progress_callback,
    )


async def extract_continuous_video_segment_frames(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    force: bool = False,
) -> tuple[ContinuousVideoSegment | None, dict[str, str]]:
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None, {}
    video_asset_id = segment.generated_video_asset_id or segment.asset_id
    if segment.status != GenerationJobStatus.SUCCEEDED or video_asset_id is None:
        raise ValueError("Somente segmentos com video gerado podem ter frames extraidos.")
    video_asset = await session.get(Asset, video_asset_id)
    if video_asset is None:
        raise ValueError("Asset de video do segmento nao encontrado.")
    errors = await _extract_and_persist_continuous_video_frames(
        session,
        segment=segment,
        video_asset=video_asset,
        force=force,
    )
    return segment, errors


async def regenerate_rejected_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    provider_name: str = "auto",
    model: str | None = None,
    progress_callback: ContinuousVideoProgressCallback | None = None,
) -> tuple[list[GenerationJob], list[ContinuousVideoSegment]]:
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return [], []
    review_status = normalize_continuous_video_review_status(
        getattr(segment, "review_status", None)
    )
    if review_status != CONTINUOUS_VIDEO_REVIEW_REJECTED:
        raise ValueError("Somente segmentos rejeitados podem ser regenerados por este fluxo.")
    return await generate_continuous_video_segment(
        session,
        project_id,
        segment_id,
        provider_name=provider_name,
        model=model,
        force=True,
        progress_callback=progress_callback,
    )


def _reset_continuous_video_segment_for_regeneration(
    segment: ContinuousVideoSegment,
    *,
    reason: str,
) -> None:
    metadata = dict(segment.metadata_json or {})
    previous_asset_id = segment.asset_id or segment.generated_video_asset_id
    if previous_asset_id is not None:
        metadata["previous_generated_video_asset_id"] = str(previous_asset_id)
    if metadata.get("initial_frame_asset_id"):
        metadata["previous_initial_frame_asset_id"] = str(metadata["initial_frame_asset_id"])
    if segment.final_frame_asset_id is not None:
        metadata["previous_final_frame_asset_id"] = str(segment.final_frame_asset_id)
    for key in (
        "initial_frame_asset_id",
        "initial_frame_storage_uri",
        "initial_frame_error",
        "final_frame_asset_id",
        "final_frame_storage_uri",
        "final_frame_error",
    ):
        metadata.pop(key, None)
    metadata.pop("error", None)
    metadata["regeneration_reason"] = reason
    metadata["regeneration_requested_at"] = datetime.now(UTC).isoformat()
    segment.status = GenerationJobStatus.PENDING
    segment.review_status = CONTINUOUS_VIDEO_REVIEW_PENDING
    segment.asset_id = None
    segment.generated_video_asset_id = None
    segment.final_frame_asset_id = None
    segment.external_operation_id = None
    segment.generation_job_id = None
    metadata["review_status"] = CONTINUOUS_VIDEO_REVIEW_PENDING
    segment.metadata_json = metadata


async def invalidate_continuous_video_downstream_segments(
    session: AsyncSession,
    project_id: UUID,
    segment_number: int,
    *,
    reason: str = "upstream_regeneration",
) -> list[ContinuousVideoSegment]:
    segments = await list_continuous_video_segments(session, project_id)
    invalidated: list[ContinuousVideoSegment] = []
    for segment in segments:
        if segment.segment_number <= segment_number:
            continue
        if continuous_video_segment_is_approved(segment):
            continue
        _reset_continuous_video_segment_for_regeneration(segment, reason=reason)
        segment.source_segment_id = None
        segment.source_video_asset_id = None
        segment.source_frame_asset_id = None
        invalidated.append(segment)
    await session.flush()
    return invalidated


async def generate_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    provider_name: str = "auto",
    model: str | None = None,
    retry_failed: bool = False,
    force: bool = False,
    progress_callback: ContinuousVideoProgressCallback | None = None,
) -> tuple[list[GenerationJob], list[ContinuousVideoSegment]]:
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return [], []
    if segment.segment_number > 1:
        previous = await get_continuous_video_segment_by_number(
            session,
            project_id,
            segment.segment_number - 1,
        )
        if not continuous_video_segment_is_approved(previous):
            raise ValueError(
                f"Aprove o segmento {segment.segment_number - 1} antes de gerar "
                f"o segmento {segment.segment_number}."
            )
        segment.source_segment_id = previous.id
        segment.source_video_asset_id = previous.asset_id
        segment.source_frame_asset_id = previous.final_frame_asset_id
    if force:
        _reset_continuous_video_segment_for_regeneration(segment, reason="force_regeneration")
        await invalidate_continuous_video_downstream_segments(
            session,
            project_id,
            segment.segment_number,
            reason="upstream_force_regeneration",
        )
    return await generate_continuous_video_segments(
        session,
        project_id,
        segment_ids=[segment.id],
        provider_name=provider_name,
        model=model,
        retry_failed=retry_failed or force,
        max_segments=1,
        progress_callback=progress_callback,
    )


async def generate_next_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    *,
    provider_name: str = "auto",
    model: str | None = None,
    retry_failed: bool = False,
    progress_callback: ContinuousVideoProgressCallback | None = None,
) -> tuple[list[GenerationJob], list[ContinuousVideoSegment]]:
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
    ordered = sorted(segments, key=lambda item: int(item.segment_number or 0))
    previous: ContinuousVideoSegment | None = None
    for segment in ordered:
        review_status = normalize_continuous_video_review_status(
            getattr(segment, "review_status", None)
        )
        if continuous_video_segment_is_approved(segment):
            previous = segment
            continue
        if review_status == CONTINUOUS_VIDEO_REVIEW_READY:
            raise ValueError(
                f"Revise e aprove o segmento {segment.segment_number} antes de continuar."
            )
        if segment.segment_number > 1 and not continuous_video_segment_is_approved(previous):
            raise ValueError(
                f"Aprove o segmento {segment.segment_number - 1} antes de gerar "
                f"o segmento {segment.segment_number}."
            )
        return await generate_continuous_video_segment(
            session,
            project_id,
            segment.id,
            provider_name=provider_name,
            model=model,
            retry_failed=retry_failed,
            progress_callback=progress_callback,
        )
    return [], []


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
