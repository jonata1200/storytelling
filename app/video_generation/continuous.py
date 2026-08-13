"""Planejamento e preparação do pacote de produção para o Google Flow.

A etapa de produção de vídeo não gera mais vídeos por IA dentro da aplicação.
Para cada segmento ela prepara um pacote (prompt + frame inicial + frame final)
que o usuário usa para criar o vídeo manualmente no Google Flow (flow.google.com).

Os valores de ``review_status`` são (valores legados são normalizados):
- ``pending``: planejado, aguardando preparação;
- ``preparing`` (legado ``generating``): frames do pacote sendo gerados (imagem);
- ``ready`` (legado ``ready_for_review``): pacote pronto (prompt + frame inicial + frame final);
- ``done`` (legado ``approved``): usuário concluiu o segmento (vídeo criado no Flow);
- ``rejected``: usuário pediu para refazer o pacote;
- ``failed``: erro técnico ao preparar o pacote.
"""

import hashlib
import json
import logging
import math
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.config.settings import get_settings
from app.core.enums import AssetKind, CostEntryType, GenerationJobStatus, ProjectStatus
from app.costs.models import CostEntry
from app.costs.service import (
    assert_project_budget_allows,
    cost_audit_metadata,
    estimate_operation_cost,
    final_budget_cost,
)
from app.observability.schemas import OperationalEventCreate
from app.observability.service import emit_project_event
from app.production.service import get_or_create_production_settings
from app.projects.repository import ProjectRepository
from app.providers.image.types import ImageGenerationRequest
from app.storage.service import apply_asset_storage_metadata
from app.storyboards.models import StoryboardFrame
from app.storytelling.models import Scene, Script, Shot
from app.video_generation.models import ContinuousVideoPlan, ContinuousVideoSegment
from app.video_generation.schemas import (
    ContinuousVideoPlanCreate,
    ContinuousVideoSegmentCreate,
)
from app.visual_bible.image_generation import (
    _generate_image_with_provider_fallback,
    _image_provider_for_project,
)
from app.visual_bible.models import Character, Location, Prop
from app.workflows.state_machine import advance_project_status

logger = logging.getLogger(__name__)
ContinuousVideoProgressCallback = Callable[
    [list[dict[str, Any]], Decimal],
    Awaitable[None] | None,
]

CONTINUOUS_VIDEO_DEFAULT_PROVIDER = "flow_assistant"
CONTINUOUS_VIDEO_DEFAULT_MODEL = "google_flow"
CONTINUOUS_VIDEO_DEFAULT_SEGMENT_SECONDS = 8
CONTINUOUS_VIDEO_MIN_APPROVED_SEGMENTS = 3
CONTINUOUS_VIDEO_FLOW_URL = "https://flow.google.com"
CONTINUOUS_VIDEO_REVIEW_PENDING = "pending"
CONTINUOUS_VIDEO_REVIEW_PREPARING = "preparing"
CONTINUOUS_VIDEO_REVIEW_READY = "ready"
CONTINUOUS_VIDEO_REVIEW_DONE = "done"
CONTINUOUS_VIDEO_REVIEW_REJECTED = "rejected"
CONTINUOUS_VIDEO_REVIEW_FAILED = "failed"
# Aliases legados: valores gravados antes da transição para o assistente Flow.
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
# Mapeamento de valores legados para os novos estados do pacote Flow.
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


def continuous_video_segment_is_approved(segment: ContinuousVideoSegment | None) -> bool:
    """True quando o usuário concluiu o segmento (vídeo criado no Google Flow)."""
    if segment is None:
        return False
    return (
        normalize_continuous_video_review_status(getattr(segment, "review_status", None))
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
    chunks_by_units: list[str] = []
    current_units: list[str] = []
    current_words = 0
    for unit in action_units:
        if (
            current_units
            and current_words >= target_words
            and len(chunks_by_units) < segment_count - 1
        ):
            chunks_by_units.append(" ".join(current_units).strip())
            current_units = []
            current_words = 0
        current_units.append(unit)
        current_words += len(unit.split())
    if current_units:
        chunks_by_units.append(" ".join(current_units).strip())
    while len(chunks_by_units) < segment_count:
        chunks_by_units.append(chunks_by_units[-1])
    return chunks_by_units[:segment_count]


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


def _segment_prompt(
    *,
    segment_number: int,
    source_text: str,
    continuity: str,
    duration_seconds: int,
) -> str:
    action = _normalize_segment_action(source_text)
    continuity_sentence = _normalize_segment_action(continuity)
    action_guidance = _segment_action_guidance(action)
    return (
        f"Prompt para Google Flow - Segmento {segment_number:02d}\n\n"
        f"Plano unico vertical 9:16, live action realista, {int(duration_seconds)}s. "
        "Sem montagem, texto na tela ou salto temporal interno.\n\n"
        "Como usar no Google Flow (flow.google.com)\n"
        "Cole este prompt, carregue o frame inicial como 'first frame' e o frame final "
        "como 'last frame', e gere o video.\n\n"
        "Acao\n"
        f"{action}\n"
        f"{action_guidance}\n\n"
        "Continuidade\n"
        f"{continuity_sentence} Comece exatamente pelo frame inicial e termine "
        "exatamente no frame final.\n\n"
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
            "flow_url": CONTINUOUS_VIDEO_FLOW_URL,
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


async def _ensure_flow_initial_frame(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
) -> None:
    """Garante o frame inicial do pacote (storyboard no 1º segmento; frame final do
    segmento anterior nos demais)."""
    metadata = dict(segment.metadata_json or {})
    if segment.segment_number <= 1:
        if segment.source_frame_asset_id is None:
            result = await session.execute(
                select(StoryboardFrame)
                .where(StoryboardFrame.project_id == project_id)
                .order_by(StoryboardFrame.frame_number)
                .limit(1)
            )
            first_frame = result.scalars().first()
            if first_frame is not None and first_frame.asset_id is not None:
                segment.source_frame_asset_id = first_frame.asset_id
                metadata["initial_frame_asset_id"] = str(first_frame.asset_id)
    else:
        previous = await get_continuous_video_segment_by_number(
            session,
            project_id,
            segment.segment_number - 1,
        )
        if previous is not None and previous.final_frame_asset_id is not None:
            segment.source_frame_asset_id = previous.final_frame_asset_id
            metadata["initial_frame_asset_id"] = str(previous.final_frame_asset_id)
    segment.metadata_json = metadata
    await session.flush()


def _segment_final_frame_prompt(segment: ContinuousVideoSegment) -> str:
    metadata = segment.metadata_json if isinstance(segment.metadata_json, dict) else {}
    action = str(metadata.get("action") or "").strip()
    continuity = str(metadata.get("continuity") or "").strip()
    names = [
        *list(metadata.get("characters") or []),
        *list(metadata.get("locations") or []),
        *list(metadata.get("props") or []),
    ]
    visual_anchor = ", ".join(str(name) for name in names if str(name).strip())
    prompt = (
        f"Frame final do Segmento {int(getattr(segment, 'segment_number', 0) or 0):02d} - "
        "estado de chegada do bloco de video.\n\n"
        "Imagem unica vertical 9:16, live action realista, sem texto na tela, "
        "sem legendas e sem marcas d'agua.\n\n"
        "Estado final\n"
        f"{action or str(getattr(segment, 'prompt', '') or '')}\n"
        f"{_segment_action_guidance(action)}\n\n"
        "Continuidade\n"
        f"{continuity}\n"
        "Este quadro sera carregado como 'last frame' no Google Flow (flow.google.com) "
        "para gerar o video do segmento."
    )
    if visual_anchor:
        prompt += f"\n\nReferencias visuais: {visual_anchor}"
    return prompt


async def _generate_segment_final_frame(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    production_settings: Any,
) -> None:
    """Gera o frame final do segmento com o provedor de imagem e persiste como Asset."""
    provider, image_model, image_dir_name = await _image_provider_for_project(
        session, project_id
    )
    provider_name = str(getattr(provider, "provider_name", "google_ai") or "google_ai")
    estimate = estimate_operation_cost(
        "image_generation",
        Decimal("1"),
        provider=provider_name,
        model=image_model,
    )
    await assert_project_budget_allows(
        session,
        project_id,
        estimate.estimated,
        stage="continuous_video_flow",
    )
    app_settings = get_settings()
    output_dir = app_settings.local_storage_path / image_dir_name / str(project_id)
    references: list[str] = []
    if segment.source_frame_asset_id is not None:
        source_asset = await session.get(Asset, segment.source_frame_asset_id)
        if source_asset is not None:
            source_uri = str(source_asset.storage_uri or "").strip()
            if source_uri:
                references.append(source_uri)
    prompt = _segment_final_frame_prompt(segment)
    request = ImageGenerationRequest(
        prompt=prompt,
        target_id=f"segmento-{segment.segment_number:03d}",
        view_type="frame_final",
        output_dir=output_dir,
        aspect_ratio=production_settings.aspect_ratio,
        resolution=production_settings.image_resolution,
        negative_prompt=CONTINUOUS_VIDEO_NEGATIVE_PROMPT,
        references=references,
        model=image_model,
    )
    image, fallback_metadata = await _generate_image_with_provider_fallback(provider, request)
    asset = Asset(
        project_id=project_id,
        artifact_id=None,
        kind=AssetKind.IMAGE,
        name=f"Frame final Segmento {segment.segment_number:03d}",
        storage_uri=image.storage_uri,
        content_type=image.content_type,
        sha256=image.sha256,
        metadata_json={
            "provider": image.provider,
            "model": image.model,
            "segment_id": str(segment.id),
            "segment_number": segment.segment_number,
            "technical_role": "continuous_video_final_frame",
            "prompt": prompt,
            **(fallback_metadata or {}),
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
    provider_cost = Decimal(str(image.estimated_cost or "0.000000"))
    total_cost = final_budget_cost(estimate.estimated, provider_cost)
    session.add(
        CostEntry(
            project_id=project_id,
            artifact_id=None,
            entry_type=CostEntryType.ESTIMATE,
            provider=image.provider,
            model=image.model,
            operation="image_generation",
            quantity=Decimal("1"),
            unit="image",
            unit_cost=estimate.unit_cost,
            total_cost=total_cost,
            currency="USD",
            metadata_json=cost_audit_metadata(
                estimated_cost=estimate.estimated,
                provider_reported_cost=provider_cost,
                final_budget_cost=total_cost,
                stage="continuous_video_flow",
                extra={
                    "segment_id": str(segment.id),
                    "segment_number": segment.segment_number,
                    "role": "final_frame_flow",
                },
            ),
        )
    )
    segment.final_frame_asset_id = asset.id
    metadata = dict(segment.metadata_json or {})
    metadata["final_frame_asset_id"] = str(asset.id)
    metadata["final_frame_storage_uri"] = asset.storage_uri
    segment.metadata_json = metadata
    await _emit_continuous_video_segment_event(
        session,
        segment=segment,
        status="frames_ready",
        provider=image.provider,
        model=image.model,
        message="Frame final do segmento gerado para o Google Flow.",
        estimated_cost=total_cost,
        details={"final_frame_asset_id": str(asset.id)},
    )
    await session.flush()


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
            operation="flow_package",
            estimated_cost=estimated_cost,
            message=message,
            details=payload,
        ),
    )


async def prepare_continuous_video_flow_package(
    session: AsyncSession,
    project_id: UUID,
    *,
    segment_ids: list[UUID] | None = None,
) -> tuple[list[ContinuousVideoSegment], dict[int, list[str]]]:
    """Prepara o pacote (prompt + frame inicial + frame final) para o Google Flow.

    Gera o frame final de cada segmento com o modelo de imagem (sem gerar vídeo).
    """
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
    production_settings = await get_or_create_production_settings(session, project_id)
    prepared: list[ContinuousVideoSegment] = []
    validation_errors: dict[int, list[str]] = {}
    for segment in segments:
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
            and segment.final_frame_asset_id is not None
        ):
            prepared.append(segment)
            continue
        segment.review_status = CONTINUOUS_VIDEO_REVIEW_GENERATING
        segment.status = GenerationJobStatus.RUNNING
        metadata = dict(segment.metadata_json or {})
        metadata.pop("error", None)
        metadata.pop("package_error", None)
        segment.metadata_json = metadata
        await session.flush()
        try:
            await _ensure_flow_initial_frame(session, project_id, segment)
            await _generate_segment_final_frame(
                session,
                project_id,
                segment,
                production_settings,
            )
        except Exception as exc:
            logger.warning(
                "continuous_video_flow_package_failed project_id=%s segment_number=%s reason=%s",
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
                provider=CONTINUOUS_VIDEO_DEFAULT_PROVIDER,
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
        metadata["flow_url"] = CONTINUOUS_VIDEO_FLOW_URL
        metadata["package_ready_at"] = datetime.now(UTC).isoformat()
        segment.metadata_json = metadata
        prepared.append(segment)
        await _emit_continuous_video_segment_event(
            session,
            segment=segment,
            status="ready",
            provider=CONTINUOUS_VIDEO_DEFAULT_PROVIDER,
            model=CONTINUOUS_VIDEO_DEFAULT_MODEL,
            message="Pacote para o Google Flow pronto: copie o prompt e os frames no Flow.",
        )
        await session.flush()
    await session.commit()
    for item in prepared:
        await session.refresh(item)
    return prepared, validation_errors


async def approve_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    note: str | None = None,
) -> ContinuousVideoSegment | None:
    """Conclui o segmento: o usuário criou o vídeo no Google Flow e marcou como feito."""
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    if (
        segment.review_status != CONTINUOUS_VIDEO_REVIEW_READY
        or segment.final_frame_asset_id is None
    ):
        raise ValueError("Somente segmentos com pacote pronto podem ser concluidos.")
    previous_status = normalize_continuous_video_review_status(
        getattr(segment, "review_status", None)
    )
    _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_APPROVED, note=note)
    segment.status = GenerationJobStatus.SUCCEEDED
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
    if next_segment is not None:
        next_segment.source_segment_id = segment.id
        next_segment.source_frame_asset_id = segment.final_frame_asset_id
        next_metadata = dict(next_segment.metadata_json or {})
        next_metadata["source_segment_id"] = str(segment.id)
        next_metadata["source_frame_asset_id"] = str(segment.final_frame_asset_id)
        next_metadata["initial_frame_asset_id"] = str(segment.final_frame_asset_id)
        if metadata.get("final_frame_storage_uri"):
            next_metadata["source_frame_storage_uri"] = metadata["final_frame_storage_uri"]
        next_metadata["continuity_source_summary"] = metadata["continuity_summary"]
        next_segment.metadata_json = next_metadata
    await _emit_continuous_video_segment_event(
        session,
        segment=segment,
        status="done",
        provider=segment.provider,
        model=segment.model,
        message="Segmento concluido: vídeo criado no Google Flow.",
    )
    await _advance_project_when_all_flow_segments_done(session, project_id, segment)
    await session.flush()
    return segment


async def mark_continuous_video_segment_done(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    note: str | None = None,
) -> ContinuousVideoSegment | None:
    return await approve_continuous_video_segment(
        session,
        project_id,
        segment_id,
        note=note,
    )


async def _advance_project_when_all_flow_segments_done(
    session: AsyncSession,
    project_id: UUID,
    changed_segment: ContinuousVideoSegment,
) -> None:
    if not continuous_video_segment_is_approved(changed_segment):
        return
    segments = await list_continuous_video_segments(session, project_id)
    if not segments or not all(continuous_video_segment_is_approved(item) for item in segments):
        return
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return
    plan = await get_or_create_continuous_video_plan(session, project_id)
    plan.status = "completed"
    advance_project_status(project, ProjectStatus.COMPLETED)


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
    """Rejeita o pacote: pede para refazer os frames do segmento e downstream."""
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    if segment.review_status not in {
        CONTINUOUS_VIDEO_REVIEW_READY,
        CONTINUOUS_VIDEO_REVIEW_APPROVED,
    }:
        raise ValueError("Somente segmentos com pacote pronto podem ser rejeitados.")
    previous_status = normalize_continuous_video_review_status(
        getattr(segment, "review_status", None)
    )
    _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_REJECTED, note=note)
    segment.status = GenerationJobStatus.PENDING
    segment.final_frame_asset_id = None
    metadata = dict(segment.metadata_json or {})
    metadata["review_decision"] = CONTINUOUS_VIDEO_REVIEW_REJECTED
    metadata["review_decision_at"] = datetime.now(UTC).isoformat()
    metadata["review_previous_status"] = previous_status
    for key in (
        "final_frame_asset_id",
        "final_frame_storage_uri",
        "package_ready_at",
        "flow_url",
    ):
        metadata.pop(key, None)
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


def _reset_continuous_video_segment_for_regeneration(
    segment: ContinuousVideoSegment,
    *,
    reason: str,
) -> None:
    metadata = dict(segment.metadata_json or {})
    if segment.final_frame_asset_id is not None:
        metadata["previous_final_frame_asset_id"] = str(segment.final_frame_asset_id)
    if metadata.get("initial_frame_asset_id"):
        metadata["previous_initial_frame_asset_id"] = str(metadata["initial_frame_asset_id"])
    for key in (
        "initial_frame_asset_id",
        "initial_frame_storage_uri",
        "final_frame_asset_id",
        "final_frame_storage_uri",
        "package_ready_at",
        "flow_url",
        "package_error",
        "error",
    ):
        metadata.pop(key, None)
    metadata["regeneration_reason"] = reason
    metadata["regeneration_requested_at"] = datetime.now(UTC).isoformat()
    segment.status = GenerationJobStatus.PENDING
    segment.review_status = CONTINUOUS_VIDEO_REVIEW_PENDING
    segment.final_frame_asset_id = None
    segment.generation_job_id = None
    segment.external_operation_id = None
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
) -> tuple[list[Any], list[ContinuousVideoSegment]]:
    """Compatibilidade: prepara o pacote para o Google Flow (sem gerar vídeo).

    Mantém a assinatura antiga para a UI; a Fase 3 substitui o uso pela função
    ``prepare_continuous_video_flow_package`` e remove esta ponte.
    """
    _ = (provider_name, model, retry_failed, max_segments, pause_after_current, progress_callback)
    segments, _validation_errors = await prepare_continuous_video_flow_package(
        session,
        project_id,
        segment_ids=segment_ids,
    )
    return [], segments


async def generate_next_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    *,
    provider_name: str = "auto",
    model: str | None = None,
    retry_failed: bool = False,
    progress_callback: ContinuousVideoProgressCallback | None = None,
) -> tuple[list[Any], list[ContinuousVideoSegment]]:
    """Compatibilidade: prepara o próximo segmento pendente/rejeitado."""
    _ = (provider_name, model, retry_failed, progress_callback)
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
    next_segment = next(
        (
            segment
            for segment in ordered
            if segment.review_status
            in {
                CONTINUOUS_VIDEO_REVIEW_PENDING,
                CONTINUOUS_VIDEO_REVIEW_REJECTED,
                CONTINUOUS_VIDEO_REVIEW_FAILED,
            }
        ),
        None,
    )
    if next_segment is None:
        return [], []
    prepared, _validation_errors = await prepare_continuous_video_flow_package(
        session,
        project_id,
        segment_ids=[next_segment.id],
    )
    return [], prepared


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
) -> tuple[list[Any], list[ContinuousVideoSegment]]:
    """Compatibilidade: (re)prepara o pacote de um único segmento."""
    _ = (provider_name, model, retry_failed, progress_callback)
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return [], []
    if force:
        _reset_continuous_video_segment_for_regeneration(segment, reason="force_regeneration")
        await invalidate_continuous_video_downstream_segments(
            session,
            project_id,
            segment.segment_number,
            reason="upstream_force_regeneration",
        )
    prepared, _validation_errors = await prepare_continuous_video_flow_package(
        session,
        project_id,
        segment_ids=[segment_id],
    )
    return [], prepared


async def retry_failed_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    provider_name: str = "auto",
    model: str | None = None,
    progress_callback: ContinuousVideoProgressCallback | None = None,
) -> tuple[list[Any], list[ContinuousVideoSegment]]:
    """Compatibilidade: reenvia (prepara) um segmento com falha."""
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return [], []
    if segment.review_status != CONTINUOUS_VIDEO_REVIEW_FAILED:
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


async def regenerate_rejected_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    provider_name: str = "auto",
    model: str | None = None,
    progress_callback: ContinuousVideoProgressCallback | None = None,
) -> tuple[list[Any], list[ContinuousVideoSegment]]:
    """Compatibilidade: (re)prepara um segmento rejeitado."""
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


async def extract_continuous_video_segment_frames(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    force: bool = False,
) -> tuple[ContinuousVideoSegment | None, dict[str, str]]:
    """Compatibilidade: os frames do pacote são gerados (não extraídos de vídeo).

    Mantido apenas para a UI; a Fase 3 remove o uso.
    """
    _ = force
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None, {}
    return segment, {}


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
    if segment.review_status == CONTINUOUS_VIDEO_REVIEW_APPROVED:
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
    # O prompt mudou: o frame final (e o pacote) ficam desatualizados.
    segment.review_status = CONTINUOUS_VIDEO_REVIEW_PENDING
    segment.status = GenerationJobStatus.PENDING
    segment.final_frame_asset_id = None
    for key in (
        "final_frame_asset_id",
        "final_frame_storage_uri",
        "package_ready_at",
        "flow_url",
        "package_error",
        "error",
    ):
        metadata.pop(key, None)
    metadata["review_status"] = CONTINUOUS_VIDEO_REVIEW_PENDING
    segment.metadata_json = metadata
    await invalidate_continuous_video_downstream_segments(
        session,
        project_id,
        segment.segment_number,
        reason="prompt_updated",
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
    """Legado: registra um resultado de vídeo já existente no segmento."""
    segment.asset_id = asset_id
    if generation_job_id is not None:
        segment.generation_job_id = generation_job_id
    if external_operation_id is not None:
        segment.external_operation_id = external_operation_id
    segment.status = GenerationJobStatus.SUCCEEDED
    await session.flush()
    return segment
