# ruff: noqa: E501, F401, I001

import asyncio
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from nicegui import ui

from app.config.settings import get_settings
from app.costs.service import estimate_operation_cost
from app.database.session import AsyncSessionLocal
from app.production.service import get_or_create_production_settings, update_production_settings
from app.ui.shared.generation_progress import (
    OPERATION_CANCELLED_MESSAGE,
    generation_progress_dialog,
    mark_dialog_task_cancelable,
    progress_ratio,
)
from app.ui.shared.page_config import (
    BLOCKING_DIALOG_PROPS,
    block_if_missing_api_keys_for_step,
    friendly_ai_error,
    is_deleted_ui_context_error,
    loading_status_message,
    safe_close_ui_element,
    show_ai_error_popup,
)
from app.ui.visual.helpers import asset_url
from app.ui.workspace.continuous_video_view_model import (
    build_continuous_video_view_model,
    continuous_video_status_label,
)
from app.ui.workspace.continuous_video_view_model import (
    CONTINUOUS_VIDEO_WORKFLOW_MODE,
)
from app.ui.workspace.video_area import render_video_area  # noqa: E402,F401
from app.video_generation.continuous import (
    approve_continuous_video_segment,
    continuous_video_segment_validation_errors,
    delete_all_continuous_video_segments,
    list_continuous_video_segments,
    plan_continuous_video_segments,
    prepare_continuous_video_package,
    regenerate_continuous_video_segment_frame,
    regenerate_continuous_video_segment_frames,
    regenerate_continuous_video_segment_prompts,
    reject_continuous_video_segment,
    remove_continuous_video_segment_frame,
    segment_frame_prompts,
    update_continuous_video_segment_frame_prompt,
    update_continuous_video_segment_prompt,
)
from app.video_generation.continuous_review import generate_continuous_video_segments

SectionTitle = Callable[[str, str, str | None, Any | None], None]
LoadingDialogFactory = Callable[[str, Any], Any]


def _copy_text_to_clipboard(text: str) -> None:
    import json

    ui.run_javascript(
        f"navigator.clipboard.writeText({json.dumps(str(text))})"
        + ".then(() => {"
        + "  const el = document.createElement('div');"
        + "  el.textContent = 'Prompt copiado!';"
        + "  el.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9999;"
        + "background:#1c221d;color:#d8dbd8;border:1px solid #343934;border-radius:10px;"
        + "padding:10px 14px;font-size:13px;box-shadow:0 6px 20px rgba(0,0,0,.4);';"
        + "  document.body.appendChild(el);"
        + "  setTimeout(() => el.remove(), 1800);"
        + "}).catch(() => { window.prompt('Copie o prompt manualmente (Ctrl+C):', '"
        + json.dumps(str(text)).replace("'", "\\'")
        + "'); })"
    )


def _download_continuous_video_segment_frames(
    segment_title: str,
    initial_frame_url: str,
    final_frame_url: str,
) -> None:
    import json
    import re

    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(segment_title or "segmento").strip()).strip("-")
    if not slug:
        slug = "segmento"
    downloads = [
        {"url": initial_frame_url, "filename": f"{slug}-frame-inicial.jpg"},
        {"url": final_frame_url, "filename": f"{slug}-frame-final.jpg"},
    ]
    ui.run_javascript(
        "(async () => {"
        f"  const downloads = {json.dumps(downloads)};"
        "  for (const item of downloads) {"
        "    const link = document.createElement('a');"
        "    link.href = item.url;"
        "    link.download = item.filename;"
        "    link.rel = 'noopener';"
        "    link.style.display = 'none';"
        "    document.body.appendChild(link);"
        "    link.click();"
        "    link.remove();"
        "    await new Promise(resolve => setTimeout(resolve, 250));"
        "  }"
        "})()"
    )


def _safe_notify(message: str, **kwargs: Any) -> bool:
    try:
        ui.notify(message, **kwargs)
    except (AssertionError, RuntimeError) as exc:
        if is_deleted_ui_context_error(exc):
            return False
        raise
    return True


def _safe_reload() -> bool:
    try:
        ui.navigate.reload()
    except (AssertionError, RuntimeError) as exc:
        if is_deleted_ui_context_error(exc):
            return False
        raise
    return True


def _safe_close_ui_element_quietly(element: object | None) -> None:
    if element is None:
        return
    try:
        close = getattr(element, "close", None)
        if callable(close):
            close()
    except (AssertionError, RuntimeError) as exc:
        if not is_deleted_ui_context_error(exc):
            raise


async def _open_loading_dialog_quietly(element: object | None) -> bool:
    if element is None:
        return False
    try:
        open_dialog = getattr(element, "open", None)
        if callable(open_dialog):
            open_dialog()
    except (AssertionError, RuntimeError) as exc:
        if is_deleted_ui_context_error(exc):
            return False
        raise
    await asyncio.sleep(0.1)
    return True


def _show_ai_error_unless_context_gone(exc: Exception) -> None:
    if is_deleted_ui_context_error(exc):
        return
    show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


async def _plan_continuous_video_segments_from_ui(
    project_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            existing_segments = await list_continuous_video_segments(session, project_id)
            has_frames_or_videos = any(
                bool(
                    getattr(seg, "source_frame_asset_id", None)
                    or getattr(seg, "final_frame_asset_id", None)
                    or getattr(seg, "generated_video_asset_id", None)
                    or getattr(seg, "asset_id", None)
                    or (
                        isinstance(getattr(seg, "metadata_json", {}), dict)
                        and (
                            seg.metadata_json.get("initial_frame_asset_id")
                            or seg.metadata_json.get("final_frame_asset_id")
                            or seg.metadata_json.get("extracted_last_frame_asset_id")
                            or seg.metadata_json.get("video_asset_id")
                        )
                    )
                )
                for seg in existing_segments
            )
            if has_frames_or_videos:
                ui.notify(
                    "O replanejamento está bloqueado porque já existem frames ou vídeos gerados.",
                    color="warning",
                )
                return

            await _open_loading_dialog_quietly(loading_dialog)
            mark_dialog_task_cancelable(loading_dialog)
            _plan, segments, validation_errors = await plan_continuous_video_segments(
                session,
                project_id,
                replace_existing=True,
            )
            await session.commit()
        if validation_errors:
            ui.notify("Segmentos criados com pontos para revisar.", color="warning")
        else:
            ui.notify(f"{len(segments)} segmento(s) planejado(s).", color="positive")
        ui.navigate.reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _delete_all_continuous_video_segments_from_ui(
    project_id: UUID,
) -> None:
    """Deleta todos os segmentos, prompts e conteudos de producao de video."""
    try:
        async with AsyncSessionLocal() as session:
            count = await delete_all_continuous_video_segments(session, project_id)
            await session.commit()
        if count == 0:
            _safe_notify("Nenhum segmento para remover.", color="info")
        else:
            _safe_notify(
                f"{count} segmento(s) removido(s).",
                color="positive",
            )
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


async def _save_continuous_video_segment_prompt_from_ui(
    project_id: UUID,
    segment_id: UUID,
    prompt: str,
    *,
    title: str | None = None,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            segment = await update_continuous_video_segment_prompt(
                session,
                project_id,
                segment_id,
                prompt=prompt,
                title=title,
            )
            await session.commit()
        if segment is None:
            ui.notify("Segmento não encontrado.", color="warning")
            return
        ui.notify("Prompt salvo.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


def _normalize_video_workflow_mode_from_ui(_value: object) -> str:
    # O modo de producao e unico: sempre o assistente de pacote de vídeo (continuous_fast).
    return CONTINUOUS_VIDEO_WORKFLOW_MODE


async def _set_video_workflow_mode_from_ui(project_id: UUID, workflow_mode: object) -> None:
    try:
        normalized_workflow_mode = _normalize_video_workflow_mode_from_ui(workflow_mode)
        async with AsyncSessionLocal() as session:
            await update_production_settings(
                session,
                project_id,
                {"workflow_mode": normalized_workflow_mode},
            )
        ui.notify("Modo de produção atualizado.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


async def _set_continuous_frame_strategy_from_ui(project_id: UUID, strategy: object) -> None:
    """Deprecated: the fast/continuity toggle was removed. Always uses continuity."""
    _safe_notify("Modo continuo e sempre ativo.", color="info")
    _safe_reload()


async def _prepare_continuous_video_package_from_ui(
    project_id: UUID,
    *,
    segment_ids: list[UUID] | None = None,
    loading_dialog: Any | None = None,
    progress_callback: Callable[[int, int, str], Any] | None = None,
) -> None:
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            prepare_kwargs: dict[str, Any] = {"segment_ids": segment_ids}
            if progress_callback is not None:
                prepare_kwargs["progress_callback"] = progress_callback
            segments, validation_errors = await prepare_continuous_video_package(
                session,
                project_id,
                **prepare_kwargs,
            )
        failed = [
            segment
            for segment in segments
            if str(getattr(segment, "review_status", "") or "").lower() == "failed"
        ]
        if failed:
            metadata = failed[0].metadata_json if isinstance(failed[0].metadata_json, dict) else {}
            message = str(metadata.get("error") or "Não foi possível preparar o pacote.")
            notified = _safe_notify(message, color="negative")
        elif validation_errors:
            first_segment_number = min(validation_errors)
            notified = _safe_notify(
                "Revise o planejamento antes de preparar: "
                + "; ".join(validation_errors[first_segment_number]),
                color="warning",
            )
        elif segments:
            notified = _safe_notify(
                "Pacote de vídeo pronto!",
                color="positive",
            )
        else:
            notified = _safe_notify("Nenhum segmento pendente para preparar.", color="info")
        if notified:
            _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _generate_continuous_video_from_ui(
    project_id: UUID,
    *,
    segment_ids: list[UUID] | None = None,
    loading_dialog: Any | None = None,
    progress_callback: Callable[[int, int, str], Any] | None = None,
) -> None:
    """Gera os vídeos reais dos segmentos via OpenRouter.

    Prepara os frames que ainda faltam e, em seguida, submete a geração de vídeo
    de cada segmento usando as referências da Biblioteca Visual.
    """
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            prepare_kwargs: dict[str, Any] = {"segment_ids": segment_ids}
            if progress_callback is not None:
                prepare_kwargs["progress_callback"] = progress_callback
            _segments, validation_errors = await prepare_continuous_video_package(
                session,
                project_id,
                **prepare_kwargs,
            )
            await session.commit()
            generated, generation_errors = await generate_continuous_video_segments(
                session,
                project_id,
                segment_ids=segment_ids,
                progress_callback=progress_callback,
            )
        failed = [
            segment
            for segment in generated
            if str(getattr(segment, "review_status", "") or "").lower() == "failed"
        ]
        if failed:
            metadata = failed[0].metadata_json if isinstance(failed[0].metadata_json, dict) else {}
            message = str(
                metadata.get("error")
                or metadata.get("video_generation_error")
                or "Não foi possível gerar os vídeos."
            )
            notified = _safe_notify(message, color="negative")
        elif generation_errors or validation_errors:
            notified = _safe_notify(
                "Alguns segmentos não foram gerados. Revise os erros antes de continuar.",
                color="warning",
            )
        elif generated:
            notified = _safe_notify(
                f"{len(generated)} vídeo(s) gerado(s) e salvos!",
                color="positive",
            )
        else:
            notified = _safe_notify(
                "Nenhum segmento pendente para gerar vídeo.",
                color="info",
            )
        if notified:
            _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _regenerate_continuous_video_segment_prompts_from_ui(
    project_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            segments = await regenerate_continuous_video_segment_prompts(
                session,
                project_id,
            )
            await session.commit()
        if segments:
            _safe_notify(
                f"{len(segments)} prompt(s) regenerado(s). Prepare o pacote novamente.",
                color="positive",
            )
        else:
            _safe_notify("Nenhum prompt pendente para regenerar.", color="info")
        _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _approve_continuous_video_segment_from_ui(
    project_id: UUID,
    segment_id: UUID,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            segment = await approve_continuous_video_segment(session, project_id, segment_id)
            await session.commit()
        if segment is None:
            _safe_notify("Segmento não encontrado.", color="warning")
            return
        _safe_notify(
            "Segmento concluído. O próximo bloco já pode continuar daqui.", color="positive"
        )
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


async def _reject_continuous_video_segment_from_ui(
    project_id: UUID,
    segment_id: UUID,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            segment = await reject_continuous_video_segment(session, project_id, segment_id)
            await session.commit()
        if segment is None:
            _safe_notify("Segmento não encontrado.", color="warning")
            return
        _safe_notify(
            "Segmento marcado para refazer. O pacote será preparado novamente.", color="warning"
        )
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


async def _regenerate_continuous_video_segment_frames_from_ui(
    project_id: UUID,
    segment_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    """Regenerate the initial and final frames for a single segment."""
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            segment = await regenerate_continuous_video_segment_frames(
                session, project_id, segment_id
            )
        if segment is None:
            _safe_notify("Segmento nao encontrado.", color="warning")
            return
        _safe_notify("Frames regenerados com sucesso.", color="positive")
        _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _remove_continuous_video_segment_frame_from_ui(
    project_id: UUID,
    segment_id: UUID,
    frame_kind: str,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            segment = await remove_continuous_video_segment_frame(
                session,
                project_id,
                segment_id,
                frame_kind,
            )
        if segment is None:
            _safe_notify("Segmento nao encontrado.", color="warning")
            return
        frame_label = "inicial" if frame_kind == "initial" else "final"
        _safe_notify(
            f"Frame {frame_label} removido. Use Gerar frames para criar apenas o que falta.",
            color="warning",
        )
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


async def _regenerate_continuous_video_segment_frame_from_ui(
    project_id: UUID,
    segment_id: UUID,
    frame_kind: str,
    *,
    loading_dialog: Any | None = None,
) -> None:
    """Regenerate only the initial or final frame for a single segment."""
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            segment = await regenerate_continuous_video_segment_frame(
                session,
                project_id,
                segment_id,
                frame_kind,
            )
        if segment is None:
            _safe_notify("Segmento nao encontrado.", color="warning")
            return
        frame_label = "inicial" if frame_kind == "initial" else "final"
        _safe_notify(f"Frame {frame_label} regenerado com sucesso.", color="positive")
        _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _save_continuous_video_segment_frame_prompts_from_ui(
    project_id: UUID,
    segment_id: UUID,
    initial_prompt: str,
    final_prompt: str,
) -> None:
    """Save custom frame prompt overrides for a segment."""
    try:
        async with AsyncSessionLocal() as session:
            segment = await update_continuous_video_segment_frame_prompt(
                session,
                project_id,
                segment_id,
                initial_frame_prompt=initial_prompt,
                final_frame_prompt=final_prompt,
            )
        if segment is None:
            _safe_notify("Segmento nao encontrado.", color="warning")
            return
        _safe_notify("Prompts de frames salvos.", color="positive")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


def _segment_frame_prompts_for_ui(segment_id: UUID, segments: list) -> dict[str, str]:
    """Get current frame prompts (override or auto) for a segment by ID."""
    for segment in segments:
        if segment.id == segment_id:
            return segment_frame_prompts(segment)
    return {"initial": "", "final": ""}


def _video_clip_asset_url(clip: Any) -> str:
    asset_id = getattr(clip, "asset_id", None)
    if asset_id is None:
        return ""
    return f"/api/v1/assets/{asset_id}/content"


def _asset_content_url(asset_id: Any) -> str:
    if asset_id is None:
        return ""
    return f"/api/v1/assets/{asset_id}/content"


def _render_continuous_media_preview(
    title: str,
    media_url: str,
    *,
    media_kind: str,
    large: bool = False,
    remove_on_click: Callable[[], Any] | None = None,
) -> None:
    if large:
        container_classes = (
            "visual-placeholder w-full aspect-[9/16] max-h-[72vh] flex items-center "
            "justify-center bg-black overflow-hidden"
        )
    else:
        container_classes = (
            "visual-placeholder max-w-[200px] aspect-[9/16] flex items-center "
            "justify-center bg-black overflow-hidden"
        )
    media_classes = "w-full h-full object-cover"
    with ui.element("div").classes("min-w-0 w-full"):
        ui.label(title).classes("text-xs text-[#8d938e]")
        with ui.element("div").classes(f"{container_classes} relative"):
            if media_url and media_kind == "video":
                ui.video(media_url, controls=True).classes("w-full h-full object-cover")
            elif media_url:
                ui.image(media_url).classes(media_classes)
                if remove_on_click is not None:
                    ui.button(
                        icon="close",
                        on_click=remove_on_click,
                    ).props("round dense unelevated").classes(
                        "absolute top-2 right-2 z-10 bg-[#d94a4a] text-white shadow-lg"
                    )
            else:
                ui.label("Indisponível").classes("text-xs text-[#8d938e]")


def _progress_ratio(done: int, total: int) -> float:
    return progress_ratio(done, total)


def _render_generation_progress_summary(
    title: str,
    generated: int,
    total: int,
    missing: int,
    detail: str,
    *,
    badge: str | None = None,
) -> None:
    with ui.element("div").classes(
        "w-full border border-[#343934] rounded-xl px-4 py-3 bg-[#0d100e] mb-3"
    ):
        with ui.row().classes("w-full items-center justify-between gap-3"):
            with ui.column().classes("gap-0"):
                ui.label(f"{title}: {generated}/{total}").classes(
                    "text-sm font-semibold text-[#d8dbd8]"
                )
                ui.label(f"Faltam {missing}. {detail}").classes("text-xs text-[#8d938e]")
            ui.badge(badge or ("pronto" if missing == 0 and total else "pendente")).classes(
                "bg-[#26301f] text-white"
                if missing == 0 and total
                else "blue-status-badge bg-[#243342]"
            )
        ui.linear_progress(
            value=_progress_ratio(generated, total),
            show_value=False,
        ).classes("w-full mt-3").props("instant-feedback rounded")


def _render_continuity_checks(checks: list[dict[str, Any]]) -> None:
    if not checks:
        return
    with ui.row().classes("w-full flex-wrap gap-2 mt-2"):
        for check in checks:
            ok = bool(check.get("ok"))
            label = str(check.get("label") or "")
            detail = str(check.get("detail") or "").strip()
            text = f"{label}: {detail}" if detail else label
            with ui.element("div").classes(
                (
                    "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs "
                    "bg-[#26301f] text-[#eaf878]"
                )
                if ok
                else (
                    "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs "
                    "bg-[#4b2a2a] text-[#ffd4d4]"
                )
            ):
                ui.icon("check_circle" if ok else "error_outline").classes("text-sm")
                ui.label(text)
