import re
import sys
import unicodedata
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.project_agent_types import (
    REVISION_TERMS,
    ProgressCallback,
    ProjectChatResult,
    _emit_progress,
)
from app.visual_bible.models import Character, Location, Prop, VisualReference
from app.visual_bible.prompts import allowed_views_for
from app.visual_bible.service import (
    approve_visual_target_and_generate_views,
    default_views_for,
    initial_view_for,
)


def _facade_attr(name: str, fallback: Any) -> Any:
    facade = sys.modules.get("app.generation.project_agent")
    return getattr(facade, name, fallback) if facade is not None else fallback


def _requests_regeneration(message: str) -> bool:
    normalized = message.lower()
    revision_terms = _facade_attr("REVISION_TERMS", REVISION_TERMS)
    return any(term in normalized for term in revision_terms) or "refa" in normalized


def _normalize_match_text(value: str) -> str:
    without_accents = "".join(
        char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", without_accents.lower()).strip()


def _requests_visual_prompt_approval(message: str) -> bool:
    normalized = _normalize_match_text(message)
    approval_terms = ("aprovar", "aprove", "aprova", "aprovado", "autorizar", "autorize")
    visual_terms = (
        "prompt",
        "imagem",
        "imagens",
        "vista",
        "vistas",
        "referência",
        "visual",
        "ativo",
        "personagem",
        "local",
        "cenario",
        "objeto",
        "prop",
    )
    return any(term in normalized for term in approval_terms) and any(
        term in normalized for term in visual_terms
    )


@dataclass(frozen=True)
class VisualChatTarget:
    kind: str
    id: UUID
    name: str


def _visual_target_kind_from_message(message: str) -> str | None:
    normalized = _normalize_match_text(message)
    if any(term in normalized for term in ("personagem", "personagens", "character")):
        return "character"
    if any(term in normalized for term in ("local", "locais", "cenario", "cenarios", "location")):
        return "location"
    if any(term in normalized for term in ("objeto", "objetos", "prop", "props")):
        return "prop"
    return None


def _requests_all_visual_targets(message: str) -> bool:
    normalized = _normalize_match_text(message)
    return any(term in normalized for term in ("todos", "todas", "tudo"))


def _requests_all_visual_views(message: str) -> bool:
    normalized = _normalize_match_text(message)
    return any(
        term in normalized
        for term in ("todas as vistas", "todos os prompts", "todas as imagens", "views")
    )


async def _visual_chat_targets(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str | None = None,
) -> list[VisualChatTarget]:
    targets: list[VisualChatTarget] = []
    for kind, model, name_attr in (
        ("character", Character, Character.name),
        ("location", Location, Location.name),
        ("prop", Prop, Prop.name),
    ):
        if target_kind is not None and kind != target_kind:
            continue
        result = await session.execute(
            select(model).where(model.project_id == project_id).order_by(name_attr)
        )
        for item in result.scalars():
            visual_item = cast(Any, item)
            targets.append(VisualChatTarget(kind, visual_item.id, str(visual_item.name)))
    return targets


def _matching_visual_chat_targets(
    message: str, targets: list[VisualChatTarget]
) -> list[VisualChatTarget]:
    normalized = _normalize_match_text(message)
    matches = [
        target
        for target in targets
        if _normalize_match_text(target.name) and _normalize_match_text(target.name) in normalized
    ]
    if matches:
        return matches
    return targets if len(targets) == 1 else []


async def _visual_reference_views_for_target(
    session: AsyncSession,
    project_id: UUID,
    target: VisualChatTarget,
) -> set[str]:
    result = await session.execute(
        select(VisualReference.view_type).where(
            VisualReference.project_id == project_id,
            VisualReference.target_kind == target.kind,
            VisualReference.target_id == target.id,
        )
    )
    return set(result.scalars())


async def _approve_visual_prompt_from_chat(
    session: AsyncSession,
    project_id: UUID,
    message: str,
    progress: ProgressCallback | None = None,
) -> ProjectChatResult:
    target_kind = _visual_target_kind_from_message(message)
    visual_chat_targets = _facade_attr("_visual_chat_targets", _visual_chat_targets)
    matching_visual_chat_targets = _facade_attr(
        "_matching_visual_chat_targets", _matching_visual_chat_targets
    )
    visual_reference_views_for_target = _facade_attr(
        "_visual_reference_views_for_target", _visual_reference_views_for_target
    )
    approve_visual_target = _facade_attr(
        "approve_visual_target_and_generate_views",
        approve_visual_target_and_generate_views,
    )
    targets = await visual_chat_targets(session, project_id, target_kind)
    if not targets:
        return ProjectChatResult(
            "Não encontrei personagens, locais ou objetos para aprovar. "
            "Crie os ativos visuais primeiro.",
            "approve_visual_prompt",
            False,
        )

    if _requests_all_visual_targets(message):
        selected_targets = targets
    else:
        selected_targets = matching_visual_chat_targets(message, targets)
    if not selected_targets:
        options = ", ".join(target.name for target in targets[:8])
        return ProjectChatResult(
            f"Preciso saber qual ativo visual você quer aprovar. Disponiveis agora: {options}.",
            "approve_visual_prompt",
            False,
        )

    created_count = 0
    approved_count = 0
    for target in selected_targets:
        existing_views = await visual_reference_views_for_target(session, project_id, target)
        if _requests_all_visual_views(message):
            view_types = [
                view for view in allowed_views_for(target.kind) if view not in existing_views
            ]
        elif not existing_views:
            view_types = [initial_view_for(target.kind)]
        else:
            view_types = [
                view for view in default_views_for(target.kind) if view not in existing_views
            ]
        if not view_types:
            approved_count += 1
            continue
        await _emit_progress(progress, f"Aprovando {target.name} e gerando imagem.")
        references = await approve_visual_target(
            session,
            project_id,
            target.kind,
            target.id,
            view_types,
        )
        if references is None:
            continue
        approved_count += 1
        created_count += len(references)

    if approved_count == 0:
        return ProjectChatResult(
            "Não consegui aprovar nenhum ativo visual com esse pedido.",
            "approve_visual_prompt",
            False,
            True,
        )
    if created_count == 0:
        return ProjectChatResult(
            f"{approved_count} ativo(s) visual(is) ja estávam com as imagens solicitadas criadas.",
            "approve_visual_prompt",
            True,
        )
    return ProjectChatResult(
        f"Aprovei {approved_count} ativo(s) visual(is) e criei {created_count} imagem(ns).",
        "approve_visual_prompt",
        True,
    )
