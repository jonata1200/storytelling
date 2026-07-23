import logging
from typing import Any
from uuid import UUID

from nicegui import ui
from sqlalchemy import select

from app.database.session import AsyncSessionLocal
from app.ui.shared.page_config import friendly_ai_error, show_ai_error_popup
from app.ui.visual.helpers import visual_reference_views_for as _visual_reference_views_for
from app.video_generation.service import generate_video_clips
from app.visual_bible.models import Character, Location, Prop, VisualReference
from app.visual_bible.service import (
    approve_visual_target_and_generate_views,
    default_views_for,
    regenerate_visual_reference,
    update_visual_target_prompt,
)

logger = logging.getLogger(__name__)

async def _approve_visual_target_from_ui(
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    view_types: list[str],
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            references = await approve_visual_target_and_generate_views(
                session,
                project_id,
                target_kind,
                target_id,
                view_types,
            )
        if references is None:
            _notify_visual_action("Não encontrei o ativo visual para aprovar.", color="negative")
            return
        if references:
            if any(_visual_reference_used_fallback(reference) for reference in references):
                _notify_visual_action(_visual_fallback_notice(), color="warning", timeout=9000)
            else:
                _notify_visual_action(
                    f"Ativo aprovado. {len(references)} vista(s) complementar(es) criada(s).",
                    color="positive",
                )
        else:
            _notify_visual_action(
                "Ativo aprovado. Todas as vistas já estavam criadas.", color="positive"
            )
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


def _visual_reference_used_fallback(reference: VisualReference) -> bool:
    metadata = reference.metadata_json if isinstance(reference.metadata_json, dict) else {}
    return bool(metadata.get("fallback_error"))


def _visual_fallback_notice() -> str:
    return (
        "Esta referência foi criada antes do bloqueio de mock. Gere novamente com um modelo "
        "real da OpenRouter para substituir o arquivo local."
    )


def _notify_visual_action(message: str, color: str, *, timeout: int | None = None) -> None:
    try:
        if timeout is None:
            ui.notify(message, color=color)
        else:
            ui.notify(message, color=color, timeout=timeout)
    except RuntimeError as exc:
        if "parent element this slot belongs to has been deleted" not in str(exc):
            raise
        logger.warning("Não foi possível notificar ação visual: contexto da página foi removido.")


async def _update_visual_prompt_from_ui(
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    canonical_prompt: str,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            target = await update_visual_target_prompt(
                session,
                project_id,
                target_kind,
                target_id,
                canonical_prompt,
                change_note="Prompt editado pela interface",
            )
        if target is None:
            _notify_visual_action("Não encontrei o ativo visual para editar.", color="negative")
            return
        _notify_visual_action("Prompt visual salvo.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        _notify_visual_action(f"Não foi possível salvar o prompt: {exc}", color="negative")


async def _regenerate_visual_reference_from_ui(
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    view_type: str,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            reference = await regenerate_visual_reference(
                session,
                project_id,
                target_kind,
                target_id,
                view_type,
            )
        if reference is None:
            _notify_visual_action(
                "Não encontrei a referência visual para gerar novamente.", color="negative"
            )
            return
        if _visual_reference_used_fallback(reference):
            _notify_visual_action(_visual_fallback_notice(), color="warning", timeout=9000)
        else:
            _notify_visual_action("Imagem gerada novamente.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


def _visual_library_cards_ready(summary: dict[str, Any]) -> bool:
    return bool(summary["characters"] or summary["locations"] or summary["props"])


def _visual_batch_requests(summary: dict[str, Any]) -> list[tuple[str, UUID, list[str]]]:
    requests: list[tuple[str, UUID, list[str]]] = []
    for target_kind, items in [
        ("character", summary["characters"]),
        ("location", summary["locations"]),
        ("prop", summary["props"]),
    ]:
        for item in items:
            existing_views = _visual_reference_views_for(summary, target_kind, item.id)
            missing_views = [
                view for view in default_views_for(target_kind) if view not in existing_views
            ]
            if missing_views:
                requests.append((target_kind, item.id, missing_views))
    return requests


async def _current_visual_batch_requests(project_id: UUID) -> list[tuple[str, UUID, list[str]]]:
    async with AsyncSessionLocal() as session:
        characters_result = await session.execute(
            select(Character).where(Character.project_id == project_id)
        )
        locations_result = await session.execute(
            select(Location).where(Location.project_id == project_id)
        )
        props_result = await session.execute(select(Prop).where(Prop.project_id == project_id))
        refs_result = await session.execute(
            select(VisualReference).where(VisualReference.project_id == project_id)
        )
        return _visual_batch_requests(
            {
                "characters": list(characters_result.scalars()),
                "locations": list(locations_result.scalars()),
                "props": list(props_result.scalars()),
                "visual_refs": list(refs_result.scalars()),
            }
        )


async def _approve_all_visual_targets_from_ui(
    project_id: UUID,
    requests: list[tuple[str, UUID, list[str]]] | None = None,
) -> None:
    try:
        current_requests = requests or await _current_visual_batch_requests(project_id)
        if not current_requests:
            _notify_visual_action(
                "Todas as imagens iniciais já estavam criadas.", color="positive"
            )
            ui.navigate.reload()
            return
        created_count = 0
        used_fallback = False
        async with AsyncSessionLocal() as session:
            for target_kind, target_id, view_types in current_requests:
                references = await approve_visual_target_and_generate_views(
                    session,
                    project_id,
                    target_kind,
                    target_id,
                    view_types,
                )
                if references is None:
                    raise ValueError("um ativo visual não foi encontrado")
                created_count += len(references)
                used_fallback = used_fallback or any(
                    _visual_reference_used_fallback(reference) for reference in references
                )
        if created_count:
            if used_fallback:
                _notify_visual_action(_visual_fallback_notice(), color="warning", timeout=9000)
            else:
                _notify_visual_action(
                    f"{created_count} imagem(ns) criada(s) em fila para a Biblioteca Visual.",
                    color="positive",
                )
        else:
            _notify_visual_action(
                "Todas as imagens iniciais já estavam criadas.", color="positive"
            )
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


async def _approve_video_prompts_from_ui(project_id: UUID, frame_ids: list[UUID]) -> None:
    try:
        async with AsyncSessionLocal() as session:
            result = await generate_video_clips(
                session,
                project_id,
                frame_ids=frame_ids,
                variants_per_frame=1,
            )
        if result is None:
            ui.notify("Não encontrei o projeto para gerar os clipes.", color="negative")
            return
        jobs, clips = result
        if clips:
            ui.notify(f"Prompts aprovados. {len(clips)} clipe(s) criado(s).", color="positive")
        elif jobs:
            ui.notify(
                "Prompts aprovados, mas a geração de vídeo ficou pendente de nova tentativa.",
                color="warning",
            )
        else:
            ui.notify("Todos os clipes selecionados já estavam criados.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))



