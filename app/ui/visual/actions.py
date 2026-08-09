import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from nicegui import ui
from sqlalchemy import select

from app.database.session import AsyncSessionLocal
from app.jobs.service import enqueue_project_step
from app.storytelling.models import Script
from app.ui.shared.page_config import (
    friendly_ai_error,
    is_deleted_ui_context_error,
    play_completion_sound,
    safe_close_ui_element,
    show_ai_error_popup,
)
from app.ui.visual.helpers import visual_reference_views_for as _visual_reference_views_for
from app.visual_bible.models import Character, Location, Prop, VisualReference
from app.visual_bible.service import (
    approve_visual_target_and_generate_views,
    default_views_for,
    generate_visual_bible,
    regenerate_visual_reference,
    update_visual_target_prompt,
)

logger = logging.getLogger(__name__)
VisualBatchProgressCallback = Callable[[int, int, str], Awaitable[None] | None]
VISUAL_PROMPT_GROUP_LABELS = (
    ("characters", "Personagens"),
    ("locations", "Locais"),
    ("props", "Objetos"),
)


async def _emit_visual_batch_progress(
    callback: VisualBatchProgressCallback | None,
    completed: int,
    total: int,
    detail: str,
) -> None:
    if callback is None:
        return
    try:
        result = callback(completed, total, detail)
        if inspect.isawaitable(result):
            await result
    except RuntimeError as exc:
        if not is_deleted_ui_context_error(exc):
            raise
        logger.warning("Visual progress ignored because the page context was removed.")


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
                play_completion_sound()
        else:
            _notify_visual_action(
                "Ativo aprovado. Todas as vistas já estávam criadas.", color="positive"
            )
        ui.navigate.reload()
    except Exception as exc:
        logger.exception(
            "Não foi possível aprovar e gerar imagens do ativo visual %s/%s no projeto %s",
            target_kind,
            target_id,
            project_id,
        )
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


def _visual_reference_used_fallback(reference: VisualReference) -> bool:
    metadata = reference.metadata_json if isinstance(reference.metadata_json, dict) else {}
    return bool(metadata.get("fallback_error"))


def _visual_fallback_notice() -> str:
    return (
        "Esta referência foi criada antes do bloqueio de mock. Gere novamente com um modelo "
        "real do provider configurado para substituir o arquivo local."
    )


def _notify_visual_action(message: str, color: str, *, timeout: int | None = None) -> None:
    try:
        if timeout is None:
            ui.notify(message, color=color)
        else:
            ui.notify(message, color=color, timeout=timeout)
    except RuntimeError as exc:
        if not is_deleted_ui_context_error(exc):
            raise
        logger.warning("Não foi possível notificar ação visual: contexto da página foi removido.")


async def _update_visual_prompt_from_ui(
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    canonical_prompt: str,
    view_type: str | None = None,
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
                view_type=view_type,
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
            play_completion_sound()
        ui.navigate.reload()
    except Exception as exc:
        logger.exception(
            "Não foi possível regenerar imagem do ativo visual %s/%s no projeto %s",
            target_kind,
            target_id,
            project_id,
        )
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


def _visual_library_cards_ready(summary: dict[str, Any]) -> bool:
    return bool(summary["characters"] or summary["locations"] or summary["props"])


def _visual_prompts_need_generation(summary: dict[str, Any]) -> bool:
    items = [*summary["characters"], *summary["locations"], *summary["props"]]
    if not items:
        return True
    return any(
        not str(
            (getattr(item, "canonical_profile", {}) or {}).get("canonical_prompt") or ""
        ).strip()
        for item in items
    )


async def _generate_all_visual_prompts_from_ui(project_id: UUID) -> None:
    await _generate_all_visual_prompts_with_progress_from_ui(project_id)


def _visual_prompt_group_progress_detail(counts: dict[str, int], completed_groups: int) -> str:
    lines: list[str] = []
    for index, (key, label) in enumerate(VISUAL_PROMPT_GROUP_LABELS, 1):
        if index <= completed_groups:
            lines.append(f"{label}: {counts.get(key, 0)} prompt(s) gerado(s).")
        else:
            lines.append(f"{label}: aguardando processamento.")
    pending_labels = [
        label
        for index, (_key, label) in enumerate(VISUAL_PROMPT_GROUP_LABELS, 1)
        if index > completed_groups
    ]
    if pending_labels:
        lines.append(f"Ainda falta: {', '.join(pending_labels).lower()}.")
    else:
        lines.append("Biblioteca Visual pronta para revisão.")
    return "\n".join(lines)


async def _generate_all_visual_prompts_with_progress_from_ui(
    project_id: UUID,
    *,
    progress_callback: VisualBatchProgressCallback | None = None,
) -> None:
    total_groups = len(VISUAL_PROMPT_GROUP_LABELS)
    try:
        await _emit_visual_batch_progress(
            progress_callback,
            0,
            total_groups,
            (
                "Agora: localizando o roteiro aprovado para orientar a Biblioteca Visual.\n"
                "Falta: extrair personagens, locais e objetos."
            ),
        )
        async with AsyncSessionLocal() as session:
            script_result = await session.execute(
                select(Script)
                .where(Script.project_id == project_id)
                .order_by(Script.created_at.desc())
                .limit(1)
            )
            script = script_result.scalars().first()
            if script is None:
                _notify_visual_action(
                    "Gere ou salve um roteiro antes de criar prompts visuais.",
                    color="warning",
                )
                return
            await _emit_visual_batch_progress(
                progress_callback,
                0,
                total_groups,
                "Roteiro localizado. A IA está extraindo personagens, locais e objetos.",
            )
            result = await generate_visual_bible(session, project_id, script.id)
        if result is None:
            _notify_visual_action(
                "Não encontrei o projeto ou roteiro para gerar prompts visuais.",
                color="negative",
            )
            return
        characters, locations, props = result
        counts = {
            "characters": len(characters),
            "locations": len(locations),
            "props": len(props),
        }
        total = len(characters) + len(locations) + len(props)
        for completed_groups in range(1, total_groups + 1):
            await _emit_visual_batch_progress(
                progress_callback,
                completed_groups,
                total_groups,
                _visual_prompt_group_progress_detail(counts, completed_groups),
            )
            await asyncio.sleep(0)
        if total:
            _notify_visual_action(
                (
                    f"{total} prompt(s) visual(is) gerado(s): "
                    f"{len(characters)} personagem(ns), {len(locations)} local(is) e "
                    f"{len(props)} objeto(s)."
                ),
                color="positive",
            )
            play_completion_sound()
        else:
            _notify_visual_action(
                "Nenhum prompt visual novo foi necessário para este projeto.",
                color="positive",
            )
        await _emit_visual_batch_progress(
            progress_callback,
            total_groups,
            total_groups,
            (
                f"Biblioteca Visual pronta: {total} prompt(s) processado(s).\n"
                f"Personagens: {len(characters)} | Locais: {len(locations)} | "
                f"Objetos: {len(props)}"
            ),
        )
        ui.navigate.reload()
    except Exception as exc:
        logger.exception("Não foi possível gerar prompts visuais no projeto %s", project_id)
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


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
    *,
    progress_callback: VisualBatchProgressCallback | None = None,
) -> None:
    try:
        current_requests = requests or await _current_visual_batch_requests(project_id)
        if not current_requests:
            _notify_visual_action(
                "Todas as imagens iniciais já estávam criadas.", color="positive"
            )
            ui.navigate.reload()
            return
        semaphore = asyncio.Semaphore(2)
        progress_lock = asyncio.Lock()
        total_images = sum(len(view_types) for _kind, _id, view_types in current_requests)
        completed_images = 0
        await _emit_visual_batch_progress(
            progress_callback,
            0,
            total_images,
            f"{total_images} imagem(ns) aguardando geração.",
        )

        async def generate_request(
            target_kind: str,
            target_id: UUID,
            view_types: list[str],
        ) -> tuple[int, bool, str | None]:
            nonlocal completed_images
            created_count = 0
            failure: str | None = None
            used_fallback = False
            try:
                async with semaphore:
                    async with AsyncSessionLocal() as session:
                        references = await approve_visual_target_and_generate_views(
                            session,
                            project_id,
                            target_kind,
                            target_id,
                            view_types,
                        )
            except Exception as exc:
                logger.exception(
                    "Não foi possível gerar imagens em lote para %s/%s no projeto %s",
                    target_kind,
                    target_id,
                    project_id,
                )
                failure = f"{target_kind}/{target_id}: {exc}"
            else:
                if references is None:
                    failure = f"{target_kind}/{target_id}: ativo visual não encontrado"
                else:
                    created_count = len(references)
                    used_fallback = any(
                        _visual_reference_used_fallback(reference) for reference in references
                    )
            async with progress_lock:
                completed_images += len(view_types)
                pending_images = max(total_images - completed_images, 0)
                detail = (
                    (
                        "Agora: imagem processada para a Biblioteca Visual.\n"
                        f"Falta: {pending_images} imagem(ns)."
                    )
                    if pending_images
                    else (
                        "Agora: todas as imagens solicitadas foram processadas.\n"
                        "Falta: recarregar a Biblioteca Visual."
                    )
                )
                await _emit_visual_batch_progress(
                    progress_callback,
                    completed_images,
                    total_images,
                    detail,
                )
            return created_count, used_fallback, failure

        results = await asyncio.gather(
            *(
                generate_request(target_kind, target_id, view_types)
                for target_kind, target_id, view_types in current_requests
            )
        )
        created_count = sum(created for created, _fallback, _failure in results)
        used_fallback = any(used for _created, used, _failure in results)
        failures = [failure for _created, _used, failure in results if failure]
        if failures:
            details = "\n".join(failures[:8])
            if len(failures) > 8:
                details += f"\n... e mais {len(failures) - 8} falha(s)."
            if created_count:
                _notify_visual_action(
                    (
                        f"{created_count} imagem(ns) criada(s), mas {len(failures)} ativo(s) "
                        "falharam. Veja os detalhes técnicos."
                    ),
                    color="warning",
                    timeout=9000,
                )
                show_ai_error_popup(
                    "Algumas imagens da Biblioteca Visual não puderam ser criadas.",
                    title="Geração parcial",
                    details=details,
                )
                ui.navigate.reload()
                return
            show_ai_error_popup(
                "Nenhuma imagem da Biblioteca Visual pôde ser criada.",
                details=details,
            )
            return
        if created_count:
            if used_fallback:
                _notify_visual_action(_visual_fallback_notice(), color="warning", timeout=9000)
            else:
                _notify_visual_action(
                    f"{created_count} imagem(ns) criada(s) em fila para a Biblioteca Visual.",
                    color="positive",
                )
                play_completion_sound()
        else:
            _notify_visual_action(
                "Todas as imagens iniciais já estávam criadas.", color="positive"
            )
        ui.navigate.reload()
    except Exception as exc:
        logger.exception("Não foi possível aprovar imagens em lote no projeto %s", project_id)
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


async def _approve_video_prompts_from_ui(
    project_id: UUID,
    frame_ids: list[UUID],
    *,
    include_canonical_references: bool = False,
    loading_dialog: Any | None = None,
    progress_callback: VisualBatchProgressCallback | None = None,
) -> None:
    if loading_dialog is not None:
        loading_dialog.open()
    try:
        await _emit_visual_batch_progress(
            progress_callback,
            0,
            len(frame_ids),
            (
                f"Agora: preparando {len(frame_ids)} clipe(s) para a fila de video.\n"
                "Falta: registrar os jobs e recarregar a etapa de video."
            ),
        )
        async with AsyncSessionLocal() as session:
            job = await enqueue_project_step(
                session,
                project_id,
                "video",
                {
                    "frame_ids": [str(frame_id) for frame_id in frame_ids],
                    "include_canonical_references": include_canonical_references,
                },
            )
        await _emit_visual_batch_progress(
            progress_callback,
            len(frame_ids),
            len(frame_ids),
            (
                "Agora: todos os clipes solicitados foram enviados para a fila.\n"
                "Falta: acompanhar o processamento ate os arquivos ficarem prontos."
            ),
        )
        ui.notify(f"Prompts aprovados. Job de video enfileirado: {job.id}.", color="positive")
        ui.navigate.reload()
        return
        result = None
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
            ui.notify("Todos os clipes selecionados já estávam criados.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        if loading_dialog is not None:
            safe_close_ui_element(loading_dialog)
