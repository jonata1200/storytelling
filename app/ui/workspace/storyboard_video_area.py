# ruff: noqa: E501

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
from app.dubbing.service import refresh_dubbing_job
from app.jobs.service import enqueue_project_step
from app.production.service import update_production_settings
from app.projects.versioning import resolve_stale_artifacts_after_regeneration
from app.storyboards.service import (
    approve_storyboard_prompt,
    approve_storyboard_prompts,
    generate_animatic_bundle,
    generate_storyboard_frames,
    storyboard_frames_need_generation,
    storyboard_prompts_need_approval,
    update_storyboard_prompt,
)
from app.storytelling.service import regenerate_scenes_and_shots
from app.ui.shared.generation_progress import (
    OPERATION_CANCELLED_MESSAGE,
    dialog_cancel_requested,
    generation_progress_dialog,
    mark_dialog_task_cancelable,
    progress_ratio,
)
from app.ui.shared.page_config import (
    BLOCKING_DIALOG_PROPS,
    block_if_missing_api_keys_for_channels,
    block_if_missing_api_keys_for_step,
    friendly_ai_error,
    is_deleted_ui_context_error,
    loading_status_message,
    safe_close_ui_element,
    show_ai_error_popup,
)
from app.ui.visual.actions import _approve_video_prompts_from_ui
from app.ui.visual.helpers import asset_url
from app.ui.workspace import storyboard_handlers as _storyboard_handlers
from app.ui.workspace.continuous_video_view_model import (
    CONTINUOUS_VIDEO_WORKFLOW_MODE,
    ContinuousVideoViewModel,
    build_continuous_video_view_model,
)
from app.ui.workspace.panels import _render_timeline_strip
from app.ui.workspace.storyboard_video_view_model import (
    _video_job_count_status,
    build_storyboard_video_view_model,
)
from app.ui.workspace.video_handlers import save_video_prompt_from_ui as _save_video_prompt_from_ui
from app.video_generation.continuous import (
    approve_continuous_video_segment,
    continuous_video_segment_validation_errors,
    extract_continuous_video_segment_frames,
    generate_continuous_video_segment,
    generate_continuous_video_segments,
    generate_next_continuous_video_segment,
    plan_continuous_video_segments,
    regenerate_rejected_continuous_video_segment,
    reject_continuous_video_segment,
    retry_failed_continuous_video_segment,
    update_continuous_video_segment_prompt,
)

SectionTitle = Callable[[str, str, str | None, Any | None], None]
LoadingDialogFactory = Callable[[str, Any], Any]


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


def _sync_storyboard_handler_dependencies() -> None:
    _storyboard_handlers.AsyncSessionLocal = AsyncSessionLocal
    _storyboard_handlers.approve_storyboard_prompt = approve_storyboard_prompt
    _storyboard_handlers.approve_storyboard_prompts = approve_storyboard_prompts
    _storyboard_handlers.generate_animatic_bundle = generate_animatic_bundle
    _storyboard_handlers.generate_storyboard_frames = generate_storyboard_frames
    _storyboard_handlers.storyboard_frames_need_generation = storyboard_frames_need_generation
    _storyboard_handlers.storyboard_prompts_need_approval = storyboard_prompts_need_approval
    _storyboard_handlers.update_storyboard_prompt = update_storyboard_prompt


async def _generate_storyboards_when_prompts_are_ready(
    session: Any,
    project_id: UUID,
    script_id: UUID,
    *,
    progress_callback: Any | None = None,
) -> int | None:
    _sync_storyboard_handler_dependencies()
    return await _storyboard_handlers.generate_storyboards_when_prompts_are_ready(
        session,
        project_id,
        script_id,
        progress_callback=progress_callback,
    )


async def _approve_storyboard_prompts_from_ui(
    project_id: UUID,
    script_id: UUID,
    *,
    loading_dialog: Any | None = None,
    progress_callback: Any | None = None,
) -> None:
    _sync_storyboard_handler_dependencies()
    await _storyboard_handlers.approve_storyboard_prompts_from_ui(
        project_id,
        script_id,
        loading_dialog=loading_dialog,
        progress_callback=progress_callback,
    )


async def _approve_storyboard_prompt_from_ui(
    project_id: UUID,
    script_id: UUID,
    shot_id: UUID,
    *,
    loading_dialog: Any | None = None,
    progress_callback: Any | None = None,
) -> None:
    _sync_storyboard_handler_dependencies()
    await _storyboard_handlers.approve_storyboard_prompt_from_ui(
        project_id,
        script_id,
        shot_id,
        loading_dialog=loading_dialog,
        progress_callback=progress_callback,
    )


async def _save_storyboard_prompt_from_ui(
    project_id: UUID,
    script_id: UUID,
    shot_id: UUID,
    prompt: str,
) -> None:
    _sync_storyboard_handler_dependencies()
    await _storyboard_handlers.save_storyboard_prompt_from_ui(
        project_id,
        script_id,
        shot_id,
        prompt,
    )


async def _plan_continuous_video_segments_from_ui(
    project_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
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
            ui.notify("Segmento n\u00e3o encontrado.", color="warning")
            return
        ui.notify("Prompt salvo.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


def _normalize_video_workflow_mode_from_ui(value: object) -> str:
    text = str(value or "").strip()
    if text == CONTINUOUS_VIDEO_WORKFLOW_MODE:
        return text
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
        ui.notify("Modo de produ\u00e7\u00e3o atualizado.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


async def _generate_continuous_video_segments_from_ui(
    project_id: UUID,
    *,
    segment_ids: list[UUID] | None = None,
    retry_failed: bool = False,
    max_segments: int | None = None,
    loading_dialog: Any | None = None,
    progress_callback: Any | None = None,
    pause_after_current: Any | None = None,
) -> None:
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            jobs, segments = await generate_continuous_video_segments(
                session,
                project_id,
                segment_ids=segment_ids,
                retry_failed=retry_failed,
                max_segments=max_segments,
                progress_callback=progress_callback,
                pause_after_current=pause_after_current,
            )
        failed = [
            segment
            for segment in segments
            if str(getattr(getattr(segment, "status", ""), "value", segment.status)).lower()
            == "failed"
        ]
        if failed:
            metadata = (
                failed[0].metadata_json if isinstance(failed[0].metadata_json, dict) else {}
            )
            message = str(metadata.get("error") or "A fila parou no segmento com falha.")
            notified = _safe_notify(message, color="negative")
        elif jobs:
            notified = _safe_notify(
                "Fila de v\u00eddeo cont\u00ednuo conclu\u00edda.",
                color="positive",
            )
        else:
            notified = _safe_notify("Nenhum segmento pendente para gerar.", color="info")
        if notified:
            _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _generate_next_continuous_video_segment_from_ui(
    project_id: UUID,
    *,
    loading_dialog: Any | None = None,
    progress_callback: Any | None = None,
) -> None:
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            jobs, _segments = await generate_next_continuous_video_segment(
                session,
                project_id,
                retry_failed=True,
                progress_callback=progress_callback,
            )
        notified = _safe_notify(
            "Pr\u00f3ximo segmento enviado para revis\u00e3o." if jobs else "Nada pendente agora.",
            color="positive" if jobs else "info",
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


async def _approve_continuous_video_segment_from_ui(
    project_id: UUID,
    segment_id: UUID,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            segment = await approve_continuous_video_segment(session, project_id, segment_id)
            await session.commit()
        if segment is None:
            _safe_notify("Segmento n\u00e3o encontrado.", color="warning")
            return
        _safe_notify("Segmento aprovado. O pr\u00f3ximo bloco j\u00e1 pode continuar daqui.", color="positive")
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
            _safe_notify("Segmento n\u00e3o encontrado.", color="warning")
            return
        _safe_notify("Segmento rejeitado. A continuidade downstream foi bloqueada.", color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


async def _retry_continuous_video_segment_from_ui(
    project_id: UUID,
    segment_id: UUID,
    *,
    loading_dialog: Any | None = None,
    progress_callback: Any | None = None,
) -> None:
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            await retry_failed_continuous_video_segment(
                session,
                project_id,
                segment_id,
                progress_callback=progress_callback,
        )
        _safe_notify("Segmento reenviado para revis\u00e3o.", color="positive")
        _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _regenerate_rejected_continuous_video_segment_from_ui(
    project_id: UUID,
    segment_id: UUID,
    *,
    loading_dialog: Any | None = None,
    progress_callback: Any | None = None,
) -> None:
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            await regenerate_rejected_continuous_video_segment(
                session,
                project_id,
                segment_id,
                progress_callback=progress_callback,
        )
        _safe_notify("Segmento regenerado para nova revis\u00e3o.", color="positive")
        _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _regenerate_continuous_video_segment_from_ui(
    project_id: UUID,
    segment_id: UUID,
    *,
    loading_dialog: Any | None = None,
    progress_callback: Any | None = None,
) -> None:
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            jobs, _segments = await generate_continuous_video_segment(
                session,
                project_id,
                segment_id,
                force=True,
                progress_callback=progress_callback,
            )
        notified = _safe_notify(
            "Segmento regenerado para nova revis\u00e3o." if jobs else "Nada para regenerar agora.",
            color="positive" if jobs else "info",
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


async def _extract_continuous_video_frames_from_ui(
    project_id: UUID,
    segment_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            segment, errors = await extract_continuous_video_segment_frames(
                session,
                project_id,
                segment_id,
                force=False,
            )
            await session.commit()
        if segment is None:
            notified = _safe_notify("Segmento n\u00e3o encontrado.", color="warning")
        elif errors:
            notified = _safe_notify(
                "N\u00e3o foi poss\u00edvel extrair todos os frames. Verifique o FFmpeg.",
                color="warning",
            )
        else:
            notified = _safe_notify("Frames extra\u00eddos do v\u00eddeo.", color="positive")
        if notified:
            _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _generate_storyboards_from_ui(
    project_id: UUID,
    script_id: UUID,
    *,
    shot_id: UUID | None = None,
    approved_only: bool = False,
    force: bool = False,
    sample_limit: int | None = None,
    loading_dialog: Any | None = None,
    progress_callback: Any | None = None,
) -> None:
    _sync_storyboard_handler_dependencies()
    await _storyboard_handlers.generate_storyboards_from_ui(
        project_id,
        script_id,
        shot_id=shot_id,
        approved_only=approved_only,
        force=force,
        sample_limit=sample_limit,
        loading_dialog=loading_dialog,
        progress_callback=progress_callback,
    )


async def _prepare_storyboard_scene_plan_from_ui(
    project_id: UUID,
    script_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    if block_if_missing_api_keys_for_step("generate_scenes_and_shots"):
        if loading_dialog is not None:
            safe_close_ui_element(loading_dialog)
        return
    if loading_dialog is not None:
        loading_dialog.open()
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            scenes = await regenerate_scenes_and_shots(session, project_id, script_id)
            if scenes is None:
                ui.notify("Não foi possível criar cenas e planos para o storyboard.", color="negative")
                return
            await resolve_stale_artifacts_after_regeneration(session, project_id)
        ui.notify("Cenas e planos preparados para o storyboard.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        if loading_dialog is not None:
            safe_close_ui_element(loading_dialog)


async def _enqueue_dubbing_from_ui(
    project_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    if block_if_missing_api_keys_for_step("dubbing"):
        return
    if loading_dialog is not None:
        loading_dialog.open()
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            job = await enqueue_project_step(session, project_id, "dubbing")
        ui.notify(f"Dublagem enfileirada: {job.id}.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        if loading_dialog is not None:
            safe_close_ui_element(loading_dialog)


async def _enqueue_finalization_from_ui(
    project_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    if block_if_missing_api_keys_for_step("finalization"):
        return
    if loading_dialog is not None:
        loading_dialog.open()
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            job = await enqueue_project_step(session, project_id, "finalization")
        ui.notify(f"Finalização enfileirada: {job.id}.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        if loading_dialog is not None:
            safe_close_ui_element(loading_dialog)


async def _refresh_dubbing_from_ui(
    project_id: UUID,
    job_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    if block_if_missing_api_keys_for_channels(("dubbing",)):
        return
    if loading_dialog is not None:
        loading_dialog.open()
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            job = await refresh_dubbing_job(session, project_id, job_id)
        if job is None:
            ui.notify("Dublagem não encontrada.", color="warning")
        elif job.status == "SUCCEEDED":
            ui.notify("Dublagem pronta.", color="positive")
        elif job.status == "FAILED":
            ui.notify("Dublagem falhou. Veja o detalhe no card.", color="negative")
        else:
            ui.notify(f"Dublagem em andamento: {job.progress}%.", color="info")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        if loading_dialog is not None:
            safe_close_ui_element(loading_dialog)


def _local_asset_file_exists(storage_uri: str) -> bool:
    if not storage_uri:
        return False
    if storage_uri.startswith(("http://", "https://", "data:")):
        return True
    storage_root = get_settings().local_storage_path.resolve()
    candidate = Path(storage_uri)
    if candidate.is_absolute():
        candidates = [candidate.resolve(strict=False)]
    else:
        candidates = []
        if candidate.parts and candidate.parts[0] == storage_root.name:
            candidates.append((storage_root.parent / candidate).resolve(strict=False))
        candidates.extend(
            [(storage_root / candidate).resolve(strict=False), candidate.resolve(strict=False)]
        )
    for path in candidates:
        try:
            path.relative_to(storage_root)
        except (OSError, RuntimeError, ValueError):
            continue
        if path.is_file():
            return True
    return False


def _storyboard_frame_image_url(summary: dict[str, Any], frame: Any) -> str:
    frame_asset_id = getattr(frame, "asset_id", None)
    if frame_asset_id is None:
        return ""
    asset_map = {asset.id: asset for asset in summary.get("assets", [])}
    asset = asset_map.get(frame_asset_id)
    if asset is None:
        return ""
    if not _local_asset_file_exists(str(asset.storage_uri or "")):
        return ""
    if str(getattr(asset, "content_type", "") or "").startswith("image/"):
        return f"/api/v1/assets/{frame_asset_id}/content"
    return asset_url(asset.storage_uri)


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
) -> None:
    container_classes = (
        "visual-placeholder w-full aspect-[9/16] max-h-[72vh] flex items-center "
        "justify-center bg-black overflow-hidden"
        if large
        else "visual-placeholder aspect-video flex items-center justify-center bg-black overflow-hidden"
    )
    media_classes = "w-full h-full object-contain" if large else "w-full h-full object-cover"
    with ui.element("div").classes("min-w-0 w-full"):
        ui.label(title).classes("text-xs text-[#8d938e]")
        with ui.element("div").classes(container_classes):
            if media_url and media_kind == "video":
                ui.video(media_url, controls=True).classes("w-full h-full")
            elif media_url:
                ui.image(media_url).classes(media_classes)
            else:
                ui.label("Indispon\u00edvel").classes("text-xs text-[#8d938e]")


def _dubbing_asset_url(job: Any) -> str:
    asset_id = getattr(job, "result_asset_id", None)
    if asset_id is None:
        return ""
    return f"/api/v1/assets/{asset_id}/content"


def _export_asset_url(export: Any) -> str:
    asset_id = getattr(export, "asset_id", None)
    if asset_id is None:
        return ""
    return f"/api/v1/assets/{asset_id}/content"


def _export_filename(export: Any) -> str:
    output_uri = str(getattr(export, "output_uri", "") or "").lower()
    suffix = ".json" if output_uri.endswith(".json") else ".mp4"
    return f"storytelling-final{suffix}"


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


def _job_status_text(job: Any) -> str:
    return _video_job_count_status(job)


def _job_frame_id(job: Any) -> UUID | None:
    payload = getattr(job, "request_payload", None)
    if not isinstance(payload, dict):
        return None
    raw_frame_id = payload.get("storyboard_frame_id")
    if raw_frame_id is None:
        return None
    try:
        return UUID(str(raw_frame_id))
    except (TypeError, ValueError):
        return None


def _latest_video_job_by_frame(video_jobs: list[Any]) -> dict[UUID, Any]:
    by_frame: dict[UUID, Any] = {}
    for job in video_jobs:
        frame_id = _job_frame_id(job)
        if frame_id is None:
            continue
        current = by_frame.get(frame_id)
        if current is not None:
            current_created_at = getattr(current, "created_at", None)
            job_created_at = getattr(job, "created_at", None)
            if (
                current_created_at is not None
                and job_created_at is not None
                and job_created_at <= current_created_at
            ):
                continue
        by_frame[frame_id] = job
    return by_frame


def _video_frame_progress_rows(view_model: Any, video_jobs: list[Any]) -> list[dict[str, Any]]:
    job_by_frame = _latest_video_job_by_frame(video_jobs)
    rows: list[dict[str, Any]] = []
    for frame in view_model.sorted_frames:
        job = job_by_frame.get(frame.id)
        status = _job_status_text(job) if job is not None else ""
        if frame.id in view_model.clip_frame_ids:
            state = "done"
            label = "Gerado"
        elif status == "running":
            state = "running"
            label = f"Processando {int(getattr(job, 'progress', 0) or 0)}%"
        elif status == "pending":
            state = "queued"
            label = "Na fila"
        elif status == "failed":
            state = "failed"
            label = "Falhou"
        else:
            state = "pending"
            label = "Falta gerar"
        rows.append(
            {
                "frame": frame,
                "job": job,
                "state": state,
                "label": label,
            }
        )
    return rows


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


def _video_cost_text(frame_count: int, duration_seconds: int) -> str:
    if frame_count <= 0 or duration_seconds <= 0:
        return "Nenhum custo previsto agora."
    estimate = estimate_operation_cost(
        "image_to_video",
        Decimal(duration_seconds),
        provider="google_ai",
        model="veo-3.1-generate-preview",
    )
    return f"Estimativa: US$ {estimate.estimated} para {frame_count} clipe(s)."


def _video_clip_cost_text(
    duration_seconds: int,
    model: str = "veo-3.1-generate-preview",
) -> str:
    if duration_seconds <= 0:
        return "Custo deste vídeo: indisponível."
    estimate = estimate_operation_cost(
        "image_to_video",
        Decimal(duration_seconds),
        provider="google_ai",
        model=model,
    )
    return f"Custo deste vídeo: US$ {estimate.estimated} ({duration_seconds}s)."


def _continuous_video_segment_cost_text(
    duration_seconds: int,
    model: str = "veo-3.1-fast-generate-preview",
) -> str:
    if duration_seconds <= 0:
        return "Custo deste segmento: indispon\u00edvel."
    estimate = estimate_operation_cost(
        "text_to_video",
        Decimal(duration_seconds),
        provider="google_ai",
        model=model,
    )
    return f"Custo deste segmento: US$ {estimate.estimated} ({duration_seconds}s)."


def _continuous_state_label(state: str) -> str:
    return {
        "pending": "Pendente",
        "sending": "Enviando",
        "processing": "Processando",
        "done": "Concluido",
        "failed": "Falhou",
        "skipped": "Ja existe",
    }.get(state, "Pendente")


def _continuous_queue_progress_dialog(
    view_model: ContinuousVideoViewModel,
) -> tuple[Any, Any, Any]:
    pause_requested = {"value": False}
    with ui.dialog().props(BLOCKING_DIALOG_PROPS) as progress_dialog, ui.card().classes(
        "p-6 w-[min(520px,92vw)]"
    ):
        with ui.row().classes("w-full items-start justify-between gap-3 shrink-0"):
            with ui.column().classes("gap-1 min-w-0"):
                ui.label("Gerando v\u00eddeo cont\u00ednuo").classes(
                    "brand-type text-2xl font-bold"
                )
                summary_label = ui.label(
                    f"{view_model.generated_segments}/{view_model.total_segments} "
                    "segmento(s) concluido(s)."
                ).classes("text-sm text-[#8d938e]")
            pause_button = ui.button(icon="close", on_click=None).props(
                "flat round dense"
            ).classes("rounded-xl")
            pause_button.tooltip("Cancelar apos o segmento atual")
        with ui.row().classes("items-center gap-3 mt-5"):
            ui.spinner(size="sm").classes("acid")
            active_label = ui.label("Preparando envio ao provider.").classes(
                "text-sm text-[#d8dbd8]"
            )
        progress_bar = ui.linear_progress(
            value=progress_ratio(view_model.generated_segments, view_model.total_segments),
            show_value=False,
        ).classes("w-full mt-4").props("instant-feedback rounded")
        remaining_label = ui.label(
            f"Custo restante: US$ {view_model.remaining_cost}"
        ).classes("text-xs text-[#8d938e] mt-2")

        def request_pause() -> None:
            pause_requested["value"] = True
            pause_button.props("disable")
            pause_button.update()
            active_label.set_text("A fila sera cancelada apos o segmento atual.")

        pause_button.on("click", request_pause)

    def update_progress(rows: list[dict[str, Any]], remaining_cost: Decimal) -> None:
        completed = sum(1 for row in rows if row.get("state") in {"done", "skipped"})
        total = len(rows)
        try:
            summary_label.set_text(f"{completed}/{total} segmento(s) concluido(s).")
            progress_bar.set_value(progress_ratio(completed, max(total, 1)))
            remaining_label.set_text(f"Custo restante: US$ {remaining_cost}")
            active_row = next(
                (
                    row
                    for row in rows
                    if str(row.get("state") or "") in {"sending", "processing"}
                ),
                None,
            )
            if active_row:
                active_label.set_text(
                    f"{active_row.get('title') or 'Segmento'}: "
                    f"{_continuous_state_label(str(active_row.get('state') or 'processing'))}."
                )
            elif completed >= total and total:
                active_label.set_text("Gera\u00e7\u00e3o conclu\u00edda.")
            else:
                active_label.set_text("Aguardando pr\u00f3ximo segmento.")
        except RuntimeError as exc:
            if not is_deleted_ui_context_error(exc):
                raise

    return (
        progress_dialog,
        update_progress,
        lambda: bool(pause_requested["value"]) or dialog_cancel_requested(progress_dialog),
    )


def _dubbing_cost_text(duration_seconds: int) -> str:
    if duration_seconds <= 0:
        return "Nenhum custo previsto agora."
    estimate = estimate_operation_cost(
        "dubbing",
        Decimal(max(1, duration_seconds)) / Decimal("60"),
        provider="elevenlabs",
        model="dubbing-v1",
    )
    return f"Estimativa: US$ {estimate.estimated} para dublagem."


def _image_cost_text(image_count: int) -> str:
    if image_count <= 0:
        return "Nenhum custo previsto agora."
    estimate = estimate_operation_cost(
        "image_generation",
        Decimal(image_count),
        provider="google_ai",
        model="gemini-3.1-flash-lite-image",
    )
    return f"Estimativa: US$ {estimate.estimated} para {image_count} imagem(ns)."


def _storyboard_frame_cost_text() -> str:
    estimate = estimate_operation_cost(
        "image_generation",
        Decimal("1"),
        provider="google_ai",
        model="gemini-3.1-flash-lite-image",
    )
    return f"Custo por storyboard: US$ {estimate.estimated}."


def render_storyboard_area(
    project_id: UUID,
    summary: dict[str, Any],
    *,
    section_title: SectionTitle,
    loading_dialog_factory: LoadingDialogFactory | None = None,
) -> None:
    script = summary.get("script")
    script_id = getattr(script, "id", None)
    prompt_previews = list(summary.get("storyboard_prompt_previews", []))
    pending_prompt_previews = [
        preview for preview in prompt_previews if not bool(preview.get("approved"))
    ]
    missing_frame_previews = [
        preview for preview in prompt_previews if not bool(preview.get("generated"))
    ]
    approved_missing_prompt_previews = [
        preview for preview in missing_frame_previews if bool(preview.get("approved"))
    ]
    storyboard_total = len(prompt_previews) or len(summary["frames"])
    storyboard_generated = (
        sum(1 for preview in prompt_previews if bool(preview.get("generated")))
        if prompt_previews
        else len(summary["frames"])
    )
    storyboard_missing = max(storyboard_total - storyboard_generated, 0)
    generation_dialog, storyboard_progress_callback = generation_progress_dialog(
        "Gerando storyboards",
        len(missing_frame_previews),
        "quadro",
        loading_status_message(
            "storyboard",
            summary["counts"],
            now="Agora: criando os quadros aprovados do storyboard.",
        ),
    )
    needs_scene_plan = (
        script_id is not None
        and not prompt_previews
        and not summary["frames"]
        and (
            int(summary["counts"].get("scenes") or 0) <= 0
            or int(summary["counts"].get("shots") or 0) <= 0
        )
    )
    if needs_scene_plan and isinstance(script_id, UUID):
        scene_plan_dialog, _update_scene_plan_progress = generation_progress_dialog(
            "Preparando storyboard",
            1,
            "etapa",
            loading_status_message(
                "storyboard",
                summary["counts"],
                now="Agora: separando o roteiro em cenas e planos.",
            ),
        )
        scene_plan_dialog.open()
        ui.timer(
            0.1,
            lambda: _prepare_storyboard_scene_plan_from_ui(
                project_id,
                script_id,
                loading_dialog=scene_plan_dialog,
            ),
            once=True,
        )
        section_title(
            "Storyboard",
            "Preparando cenas e planos a partir do roteiro atual.",
            None,
            None,
        )
        with ui.element("div").classes(
            "w-full border border-blue-800 bg-blue-950/40 rounded-xl px-4 py-3"
        ):
            with ui.row().classes("w-full items-center gap-3"):
                ui.spinner(size="sm").classes("text-blue-400")
                ui.label("A IA está preparando a estrutura do storyboard.").classes(
                    "text-sm text-blue-200"
                )
        return
    prompt_dialog: Any | None = None
    if script_id is not None and prompt_previews:
        active_script_id: UUID = script_id
        with (
            ui.dialog().props(BLOCKING_DIALOG_PROPS) as prompt_dialog,
            ui.card().classes("entity-card rounded-2xl p-6 w-[min(680px,94vw)] max-h-[80vh]"),
        ):
            ui.label("Aprovar prompts de storyboard").classes("brand-type text-2xl font-bold")
            ui.label(
                f"Confirme a aprovação dos prompts para gerar {len(missing_frame_previews)} quadro(s)."
            ).classes("text-sm text-[#8d938e]")

            with ui.element("div").classes(
                "border border-[#343934] rounded-xl p-4 mt-4"
            ):
                with ui.row().classes("w-full items-center justify-between gap-3"):
                    with ui.column().classes("gap-1"):
                        ui.label(f"{len(prompt_previews)} prompt(s) total").classes(
                            "text-sm font-semibold text-[#d8dbd8]"
                        )
                        approved_count = sum(
                            1 for p in prompt_previews if bool(p.get("approved"))
                        )
                        ui.label(
                            f"{approved_count} aprovado(s), {len(pending_prompt_previews)} pendente(s)"
                        ).classes("text-xs text-[#8d938e]")
                    ui.badge(
                        "pendente" if pending_prompt_previews else "aprovado"
                    ).classes(
                        "bg-[#5aa3f0]" if pending_prompt_previews else "bg-[#26301f] text-white"
                    )
                ui.label(_image_cost_text(len(missing_frame_previews))).classes(
                    "text-xs text-[#8d938e] mt-2"
                )

            async def confirm_storyboard_prompts() -> None:
                safe_close_ui_element(prompt_dialog)
                await _approve_storyboard_prompts_from_ui(
                    project_id,
                    script_id,
                    loading_dialog=generation_dialog,
                    progress_callback=storyboard_progress_callback,
                )

            with ui.row().classes("w-full justify-end gap-2 mt-6 pt-4 border-t border-[#343934]"):
                ui.button("Fechar", on_click=prompt_dialog.close).props("flat no-caps")
                if pending_prompt_previews:
                    ui.button(
                        f"Aprovar {len(pending_prompt_previews)} prompt(s) e gerar",
                        icon="check_circle",
                        on_click=confirm_storyboard_prompts,
                    ).props("unelevated no-caps").classes("acid-bg rounded-xl")
    if prompt_dialog is not None:
        storyboard_action_label = (
            f"Aprovar prompts pendentes ({len(pending_prompt_previews)})"
            if pending_prompt_previews
            else "Ver prompts aprovados"
        )
        with ui.row().classes("w-full items-end justify-between gap-4 mb-2"):
            with ui.column().classes("gap-1"):
                ui.label("Storyboard").classes("brand-type text-3xl font-bold")
                ui.label("Planeje enquadramentos e ritmo antes de gerar os clipes.").classes(
                    "text-sm text-[#8e948f]"
                )
            ui.button(
                storyboard_action_label,
                icon="fact_check",
                on_click=prompt_dialog.open,
            ).props("unelevated no-caps").classes("acid-bg rounded-xl shrink-0")
    else:
        section_title(
            "Storyboard",
            "Planeje enquadramentos e ritmo antes de gerar os clipes.",
            None,
            None,
        )
    if storyboard_total:
        _render_generation_progress_summary(
            "Quadros do storyboard",
            storyboard_generated,
            storyboard_total,
            storyboard_missing,
            (
                f"{len(pending_prompt_previews)} prompt(s) pendente(s). "
                f"{_image_cost_text(storyboard_missing)}"
            ),
        )
    if script_id is not None and prompt_previews and not pending_prompt_previews:
        with ui.row().classes("w-full items-center justify-end gap-2 mb-2"):
            if not pending_prompt_previews and missing_frame_previews:
                if len(missing_frame_previews) > 3:
                    ui.button(
                        "Gerar teste (3)",
                        icon="science",
                        on_click=lambda: _generate_storyboards_from_ui(
                            project_id,
                            script_id,
                            sample_limit=3,
                            loading_dialog=generation_dialog,
                            progress_callback=storyboard_progress_callback,
                        ),
                    ).props("flat no-caps").classes("rounded-xl")
                ui.button(
                    f"Gerar storyboards aprovados ({len(missing_frame_previews)})",
                    icon="auto_awesome",
                    on_click=lambda: _generate_storyboards_from_ui(
                        project_id,
                        script_id,
                        loading_dialog=generation_dialog,
                        progress_callback=storyboard_progress_callback,
                    ),
                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
            if summary["frames"] and not pending_prompt_previews:
                ui.button(
                    "Gerar novamente",
                    icon="refresh",
                    on_click=lambda: _generate_storyboards_from_ui(
                        project_id,
                        script_id,
                        force=True,
                        loading_dialog=generation_dialog,
                        progress_callback=storyboard_progress_callback,
                    ),
                ).props("flat no-caps").classes("text-[#d8dbd8]")
    visible_prompt_previews = pending_prompt_previews + approved_missing_prompt_previews
    if visible_prompt_previews:
        with ui.column().classes("w-full gap-3 mb-2"):
            with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
                for preview in visible_prompt_previews:
                    approved = bool(preview.get("approved"))
                    shot_id = preview["shot_id"]
                    with (
                        ui.dialog().props(BLOCKING_DIALOG_PROPS) as prompt_detail_dialog,
                        ui.card().classes(
                            "entity-card rounded-2xl p-6 w-[min(820px,94vw)] "
                            "h-[min(760px,86vh)] flex flex-col overflow-hidden"
                        ),
                    ):
                        with ui.column().classes("w-full gap-1 shrink-0"):
                            ui.label(
                                "Cena "
                                f"{int(preview.get('scene_number') or 0):02d} · "
                                f"Plano {int(preview.get('shot_number') or 0):02d}"
                            ).classes("brand-type text-2xl font-bold")
                            prompt_origin_label = (
                                "Prompt customizado"
                                if bool(preview.get("custom_prompt"))
                                else "Prompt gerado automaticamente"
                            )
                            ui.label(prompt_origin_label).classes("text-sm text-[#8d938e]")
                        with ui.column().classes("w-full flex-1 min-h-0 mt-3"):
                            prompt_input = (
                                ui.textarea(
                                    "Prompt do storyboard",
                                    value=str(preview.get("prompt") or ""),
                                )
                                .props("outlined")
                                .classes("storyboard-prompt-textarea w-full flex-1 min-h-0")
                            )

                        async def save_single_prompt(
                            shot_id: UUID = shot_id,
                            prompt_input: Any = prompt_input,
                            dialog: Any = prompt_detail_dialog,
                        ) -> None:
                            new_prompt = str(prompt_input.value or "").strip()
                            if not new_prompt:
                                ui.notify("Informe um prompt antes de salvar.", color="warning")
                                return
                            safe_close_ui_element(dialog)
                            await _save_storyboard_prompt_from_ui(
                                project_id,
                                active_script_id,
                                shot_id,
                                new_prompt,
                            )

                        with ui.row().classes(
                            "w-full justify-end gap-2 mt-4 pt-3 border-t border-[#343934] shrink-0"
                        ):
                            ui.button("Cancelar", on_click=prompt_detail_dialog.close).props(
                                "flat no-caps"
                            )
                            ui.button(
                                "Salvar",
                                icon="save",
                                on_click=save_single_prompt,
                            ).props("unelevated no-caps").classes("acid-bg rounded-xl")
                    with (
                        ui.element("div")
                        .classes("entity-card rounded-2xl p-4 cursor-pointer")
                        .on("click", prompt_detail_dialog.open)
                    ):
                        with ui.row().classes("w-full items-start justify-between gap-3"):
                            with ui.column().classes("gap-0 min-w-0"):
                                ui.label(
                                    "Cena "
                                    f"{int(preview.get('scene_number') or 0):02d} · "
                                    f"Plano {int(preview.get('shot_number') or 0):02d}"
                                ).classes("text-sm font-semibold")
                                ui.label(f"{int(preview.get('duration_seconds') or 0)}s").classes(
                                    "text-xs acid"
                                )
                                ui.label(_storyboard_frame_cost_text()).classes(
                                    "text-xs text-[#8d938e]"
                                )
                            ui.badge("aprovado" if approved else "pendente").classes(
                                "bg-[#26301f] text-white" if approved else "bg-[#5aa3f0]"
                            )
                        ui.label(str(preview.get("prompt") or "")).classes(
                            "text-xs text-[#aeb4af] whitespace-pre-wrap mt-3 line-clamp-6"
                        )
                        _render_continuity_checks(list(preview.get("continuity_checks") or []))
                        with ui.row().classes("w-full items-center justify-between gap-2 mt-2"):
                            if script_id is not None and not approved:
                                approve_button = (
                                    ui.button(
                                        "Aprovar prompt",
                                        icon="check_circle",
                                    )
                                    .props("unelevated dense no-caps")
                                    .classes("acid-bg rounded-xl")
                                )
                                approve_button.on(
                                    "click.stop",
                                    lambda shot_id=shot_id: _approve_storyboard_prompt_from_ui(
                                        project_id,
                                        script_id,
                                        shot_id,
                                        loading_dialog=generation_dialog,
                                        progress_callback=storyboard_progress_callback,
                                    ),
                                )
                            elif (
                                script_id is not None
                                and approved
                                and not bool(preview.get("generated"))
                            ):
                                generate_button = (
                                    ui.button(
                                        "Gerar quadro",
                                        icon="auto_awesome",
                                    )
                                    .props("unelevated dense no-caps")
                                    .classes("acid-bg rounded-xl")
                                )
                                generate_button.on(
                                    "click.stop",
                                    lambda shot_id=shot_id: _generate_storyboards_from_ui(
                                        project_id,
                                        script_id,
                                        shot_id=shot_id,
                                        approved_only=True,
                                        loading_dialog=generation_dialog,
                                        progress_callback=storyboard_progress_callback,
                                    ),
                                )
    with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
        for frame in sorted(summary["frames"], key=lambda f: f.frame_number):
            image_url = _storyboard_frame_image_url(summary, frame)
            with ui.element("div").classes("entity-card rounded-2xl overflow-hidden"):
                with ui.element("div").classes(
                    "storyboard-frame-media visual-placeholder w-full aspect-[9/16] p-0 "
                    "relative overflow-hidden bg-black"
                ):
                    if image_url:
                        ui.image(image_url).classes(
                            "storyboard-frame-image absolute inset-0 w-full h-full object-cover"
                        ).props("fit=cover")
                    else:
                        ui.icon("photo_camera").classes("text-5xl text-[#bdc77b]")
                    if script_id is not None:
                        ui.button(
                            icon="refresh",
                            on_click=lambda shot_id=frame.shot_id: _generate_storyboards_from_ui(
                                project_id,
                                script_id,
                                shot_id=shot_id,
                                force=True,
                                loading_dialog=generation_dialog,
                                progress_callback=storyboard_progress_callback,
                            ),
                        ).props("round unelevated dense").classes(
                            "acid-bg absolute right-3 top-3 z-10 shadow-lg"
                        ).tooltip("Gerar novamente este storyboard")
                with ui.column().classes("p-4 gap-2"):
                    ui.label(f"PLANO {frame.frame_number:02d} · {frame.duration_seconds}s").classes(
                        "text-xs acid font-semibold"
                    )
                    ui.label(_storyboard_frame_cost_text()).classes("text-xs text-[#8d938e]")
                    ui.label(frame.prompt).classes("text-sm text-[#d1d4d1] line-clamp-3")
                    if script_id is not None:
                        ui.button(
                            "Gerar novamente",
                            icon="refresh",
                            on_click=lambda shot_id=frame.shot_id: _generate_storyboards_from_ui(
                                project_id,
                                script_id,
                                shot_id=shot_id,
                                force=True,
                                loading_dialog=generation_dialog,
                                progress_callback=storyboard_progress_callback,
                            ),
                        ).props("unelevated dense no-caps").classes("acid-bg self-start rounded-xl")
        if not summary["frames"]:
            ui.label(
                "O Diretor IA pode criar os quadros quando roteiro e ativos estiverem prontos."
            ).classes("text-[#858b86]")


def render_video_area(
    project_id: UUID,
    summary: dict[str, Any],
    *,
    section_title: SectionTitle,
    loading_dialog_factory: LoadingDialogFactory | None = None,
) -> None:
    continuous_view_model = build_continuous_video_view_model(summary)
    view_model = build_storyboard_video_view_model(summary)
    pending_frames = view_model.pending_frames
    video_prompt_by_frame_id = view_model.video_prompt_by_frame_id
    frame_by_id = view_model.frame_by_id
    generated_count = view_model.generated_count
    total_frames = view_model.total_frames
    active_video_job_count = view_model.queued_video_jobs + view_model.running_video_jobs
    video_jobs = list(summary.get("video_jobs", []))
    video_progress_rows = _video_frame_progress_rows(view_model, video_jobs)
    active_video_frame_ids = {
        row["frame"].id for row in video_progress_rows if row["state"] in {"running", "queued"}
    }
    timeline = summary["timeline"]
    total_duration = view_model.total_duration
    has_active_jobs = active_video_job_count > 0
    loading_dialog, video_progress_callback = generation_progress_dialog(
        "Gerando clipes",
        len(pending_frames),
        "clipe",
        loading_status_message(
            "video",
            summary["counts"],
            now="Agora: enviando os clipes aprovados para a fila de video.",
        ),
    )
    pending_duration = sum(
        int(getattr(frame, "duration_seconds", 0) or 0) for frame in pending_frames
    )
    continuous_segments = list(summary.get("continuous_video_segments", []))
    segment_total_duration = sum(
        int(getattr(segment, "duration_seconds", 0) or 0) for segment in continuous_segments
    )
    segment_plan_dialog, _segment_plan_progress_callback = generation_progress_dialog(
        "Planejando segmentos",
        1,
        "etapa",
        "Agora: separando o roteiro em blocos de v\u00eddeo cont\u00ednuo.",
    )
    continuous_generation_dialog, continuous_progress_callback, pause_after_current = (
        _continuous_queue_progress_dialog(continuous_view_model)
    )
    frame_extraction_dialog, _frame_extraction_progress_callback = generation_progress_dialog(
        "Extraindo frames",
        1,
        "etapa",
        "Agora: extraindo previews do video gerado.",
    )

    if continuous_view_model.is_continuous_mode:
        with ui.row().classes("w-full items-start justify-between gap-4 mb-2"):
            with ui.column().classes("gap-1 min-w-0"):
                ui.label("Produ\u00e7\u00e3o de v\u00eddeo").classes("brand-type text-3xl font-bold")
                ui.label(
                    "Gere blocos sequenciais com Veo Fast a partir do roteiro e da Biblioteca Visual."
                ).classes("text-sm text-[#8e948f]")
            with ui.column().classes("items-end gap-2 shrink-0"):
                ui.button(
                    "Replanejar" if continuous_segments else "Planejar segmentos",
                    icon="view_timeline",
                    on_click=lambda: _plan_continuous_video_segments_from_ui(
                        project_id,
                        loading_dialog=segment_plan_dialog,
                    ),
                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
                if continuous_segments:
                    ui.label(
                        f"Custo restante: US$ {continuous_view_model.remaining_cost}"
                    ).classes("text-xs text-[#8d938e]")
    else:
        section_title(
            "Produ\u00e7\u00e3o de v\u00eddeo",
            "Transforme cada quadro aprovado em clipes e acompanhe a montagem final.",
            None,
            None,
        )

    with ui.element("div").classes(
        "w-full mt-2" if continuous_view_model.is_continuous_mode else "hidden"
    ):
        if continuous_segments:
            with ui.row().classes("w-full items-center justify-between flex-wrap gap-3 mt-3"):
                with ui.row().classes("flex-wrap gap-2"):
                    ui.badge(f"{len(continuous_segments)} segmento(s)").classes(
                        "blue-status-badge bg-[#243342]"
                    )
                    ui.badge(f"{segment_total_duration}s").classes(
                        "blue-status-badge bg-[#26301f]"
                    )
                    ui.badge("Veo 3.1 Fast").classes("blue-status-badge bg-[#30362b]")
                with ui.column().classes("gap-2 items-end"):
                    with ui.row().classes("gap-2 justify-end flex-wrap"):
                        next_button = ui.button(
                            "Gerar pr\u00f3ximo",
                            icon="skip_next",
                            on_click=lambda: _generate_next_continuous_video_segment_from_ui(
                                project_id,
                                loading_dialog=continuous_generation_dialog,
                                progress_callback=continuous_progress_callback,
                            ),
                        ).props("unelevated no-caps").classes("acid-bg rounded-xl")
                        continue_button = ui.button(
                            "Continuar do aprovado",
                            icon="restart_alt",
                            on_click=lambda: _generate_next_continuous_video_segment_from_ui(
                                project_id,
                                loading_dialog=continuous_generation_dialog,
                                progress_callback=continuous_progress_callback,
                            ),
                        ).props("flat no-caps").classes("rounded-xl")
                        if not continuous_view_model.can_generate_next:
                            next_button.props("disable")
                            next_button.tooltip(
                                "Gere o planejamento ou aprove o segmento pronto para revisar."
                            )
                        if not continuous_view_model.can_generate_next:
                            continue_button.props("disable")
                            continue_button.tooltip(
                                "A continuidade s\u00f3 avan\u00e7a ap\u00f3s aprovar o segmento anterior."
                            )

            approved_segment_numbers = {
                int(getattr(segment, "segment_number", 0) or 0)
                for segment in continuous_segments
                if str(getattr(segment, "review_status", "") or "").lower() == "approved"
            }
            with ui.grid().classes("w-full grid-cols-1 xl:grid-cols-2 gap-4 mt-4"):
                for segment in continuous_segments:
                    metadata = (
                        getattr(segment, "metadata_json", {})
                        if isinstance(getattr(segment, "metadata_json", {}), dict)
                        else {}
                    )
                    names = [
                        *list(metadata.get("characters") or []),
                        *list(metadata.get("locations") or []),
                        *list(metadata.get("props") or []),
                    ]
                    visual_summary = ", ".join(str(name) for name in names if str(name).strip())
                    validation_errors = continuous_video_segment_validation_errors(segment)
                    status_value = str(
                        getattr(segment, "review_status", None)
                        or getattr(getattr(segment, "status", ""), "value", segment.status)
                    ).lower()
                    is_generating_segment = status_value in {
                        "generating",
                        "running",
                        "sending",
                        "processing",
                    }
                    segment_number = int(getattr(segment, "segment_number", 0) or 0)
                    can_use_previous = segment_number <= 1 or (
                        segment_number - 1 in approved_segment_numbers
                    )
                    generated_video_url = _asset_content_url(
                        getattr(segment, "generated_video_asset_id", None)
                        or getattr(segment, "asset_id", None)
                        or (
                            metadata.get("previous_generated_video_asset_id")
                            if is_generating_segment
                            else None
                        )
                    )
                    initial_frame_url = _asset_content_url(
                        metadata.get("initial_frame_asset_id")
                        or getattr(segment, "source_frame_asset_id", None)
                        or (
                            metadata.get("previous_initial_frame_asset_id")
                            if is_generating_segment
                            else None
                        )
                    )
                    final_frame_url = _asset_content_url(
                        getattr(segment, "final_frame_asset_id", None)
                        or metadata.get("final_frame_asset_id")
                        or (
                            metadata.get("previous_final_frame_asset_id")
                            if is_generating_segment
                            else None
                        )
                    )
                    with (
                        ui.dialog().props(BLOCKING_DIALOG_PROPS) as segment_prompt_dialog,
                        ui.card().classes(
                            "entity-card rounded-2xl p-6 w-[min(820px,94vw)] "
                            "h-[min(760px,86vh)] flex flex-col overflow-hidden"
                        ),
                    ):
                        with ui.column().classes("w-full gap-1 shrink-0"):
                            ui.label(getattr(segment, "title", "") or "Segmento").classes(
                                "brand-type text-2xl font-bold"
                            )
                            ui.label(
                                f"{int(getattr(segment, 'duration_seconds', 0) or 0)}s "
                                f"\u00b7 {getattr(segment, 'model', '')}"
                            ).classes("text-sm text-[#8d938e]")
                        with ui.column().classes("w-full flex-1 min-h-0 mt-3"):
                            segment_prompt_input = (
                                ui.textarea(
                                    "Prompt de v\u00eddeo",
                                    value=str(getattr(segment, "prompt", "") or ""),
                                )
                                .props("outlined")
                                .classes("storyboard-prompt-textarea w-full flex-1 min-h-0")
                            )

                        async def save_segment_prompt(
                            segment_id: UUID = segment.id,
                            prompt_input: Any = segment_prompt_input,
                            dialog: Any = segment_prompt_dialog,
                        ) -> None:
                            new_prompt = str(prompt_input.value or "").strip()
                            if not new_prompt:
                                ui.notify("Informe um prompt antes de salvar.", color="warning")
                                return
                            safe_close_ui_element(dialog)
                            await _save_continuous_video_segment_prompt_from_ui(
                                project_id,
                                segment_id,
                                new_prompt,
                            )

                        with ui.row().classes(
                            "w-full justify-end gap-2 mt-4 pt-3 border-t border-[#343934] shrink-0"
                        ):
                            ui.button(
                                "Cancelar",
                                on_click=segment_prompt_dialog.close,
                            ).props("flat no-caps")
                            ui.button(
                                "Salvar",
                                icon="save",
                                on_click=save_segment_prompt,
                            ).props("unelevated no-caps").classes("acid-bg rounded-xl")

                    with (
                        ui.dialog().props(BLOCKING_DIALOG_PROPS) as segment_media_dialog,
                        ui.card().classes(
                            "entity-card rounded-2xl p-5 w-[min(1180px,96vw)] "
                            "h-[min(880px,92vh)] flex flex-col overflow-hidden"
                        ),
                    ):
                        with ui.row().classes("w-full items-center justify-between gap-3 shrink-0"):
                            with ui.column().classes("gap-1 min-w-0"):
                                ui.label(
                                    getattr(segment, "title", "")
                                    or f"Segmento {segment.segment_number:02d}"
                                ).classes("brand-type text-2xl font-bold")
                                ui.label("Frame inicial, video e frame final").classes(
                                    "text-xs text-[#8d938e]"
                                )
                            ui.button(
                                icon="close",
                                on_click=segment_media_dialog.close,
                            ).props("flat round dense")
                        with ui.grid().classes(
                            "w-full grid-cols-1 lg:grid-cols-3 gap-4 mt-4 flex-1 min-h-0 overflow-y-auto"
                        ):
                            _render_continuous_media_preview(
                                "Frame inicial",
                                initial_frame_url,
                                media_kind="image",
                                large=True,
                            )
                            _render_continuous_media_preview(
                                "V\u00eddeo",
                                generated_video_url,
                                media_kind="video",
                                large=True,
                            )
                            _render_continuous_media_preview(
                                "Frame final",
                                final_frame_url,
                                media_kind="image",
                                large=True,
                            )

                    with (
                        ui.element("div")
                        .classes("entity-card rounded-2xl p-4")
                    ):
                        with ui.row().classes("w-full items-start justify-between gap-3"):
                            with ui.column().classes("gap-1 min-w-0"):
                                ui.label(
                                    getattr(segment, "title", "")
                                    or f"Segmento {segment.segment_number:02d}"
                                ).classes("font-semibold")
                                ui.label(
                                    _continuous_video_segment_cost_text(
                                        int(getattr(segment, "duration_seconds", 0) or 0),
                                        str(getattr(segment, "model", "") or ""),
                                    )
                                ).classes("text-xs text-[#8d938e]")
                            ui.badge(status_value or "pendente").classes(
                                "bg-[#26301f] text-[#eaf878]"
                                if status_value in {"approved", "ready_for_review", "succeeded"}
                                else (
                                    "bg-[#4b2a2a] text-[#ffd4d4]"
                                    if status_value in {"failed", "rejected"}
                                    else "blue-status-badge bg-[#243342]"
                                )
                            )
                        if generated_video_url or initial_frame_url or final_frame_url:
                            with ui.grid().classes("w-full grid-cols-1 md:grid-cols-3 gap-3 mt-3"):
                                _render_continuous_media_preview(
                                    "Frame inicial",
                                    initial_frame_url,
                                    media_kind="image",
                                )
                                _render_continuous_media_preview(
                                    "V\u00eddeo",
                                    generated_video_url,
                                    media_kind="video",
                                )
                                _render_continuous_media_preview(
                                    "Frame final",
                                    final_frame_url,
                                    media_kind="image",
                                )
                        if not can_use_previous:
                            ui.label(
                                f"Aprove o segmento {segment_number - 1:02d} antes de gerar este."
                            ).classes("text-xs text-[#ffddb4] mt-2")
                        if metadata.get("error"):
                            ui.label(str(metadata.get("error"))[:240]).classes(
                                "text-xs text-[#ffb4b4] mt-2"
                            )
                        if metadata.get("final_frame_error"):
                            ui.label(
                                "Frame final indispon\u00edvel: "
                                + str(metadata.get("final_frame_error"))[:220]
                            ).classes("text-xs text-[#ffddb4] mt-2")
                        if metadata.get("initial_frame_error"):
                            ui.label(
                                "Frame inicial indispon\u00edvel: "
                                + str(metadata.get("initial_frame_error"))[:220]
                            ).classes("text-xs text-[#ffddb4] mt-2")
                        if metadata.get("continuity_source_summary"):
                            ui.label(str(metadata.get("continuity_source_summary"))[:260]).classes(
                                "text-xs text-[#8d938e] mt-2"
                            )
                        if validation_errors:
                            ui.label("; ".join(validation_errors)).classes(
                                "text-xs text-[#ffb4b4] mt-2"
                            )
                        if is_generating_segment:
                            with ui.row().classes(
                                "items-center gap-2 mt-3 text-sm text-[#d1d4d1]"
                            ):
                                ui.spinner(size="sm").classes("acid")
                                ui.label(
                                    "Gerando nova vers\u00e3o do segmento. A revis\u00e3o volta assim que o v\u00eddeo terminar."
                                )
                        ui.label(str(metadata.get("action") or "")).classes(
                            "text-sm text-[#d1d4d1] line-clamp-3 mt-3"
                        )
                        if visual_summary:
                            ui.label(visual_summary).classes("text-xs text-[#8d938e] mt-2")
                        ui.label(str(getattr(segment, "prompt", "") or "")).classes(
                            "text-xs text-[#aeb4af] whitespace-pre-wrap mt-3 line-clamp-5"
                        )
                        with ui.row().classes("w-full justify-end mt-2"):
                            if generated_video_url or initial_frame_url or final_frame_url:
                                ui.button(
                                    "Visualizar",
                                    icon="open_in_full",
                                    on_click=segment_media_dialog.open,
                                ).props("flat dense no-caps").classes("rounded-xl")
                            if is_generating_segment:
                                generating_button = ui.button(
                                    "Gerando",
                                    icon="hourglass_empty",
                                ).props("unelevated dense no-caps disable").classes(
                                    "acid-bg rounded-xl"
                                )
                                generating_button.tooltip(
                                    "A gera\u00e7\u00e3o esta em andamento. Atualize para verificar o resultado."
                                )
                                ui.button(
                                    "Atualizar",
                                    icon="refresh",
                                    on_click=_safe_reload,
                                ).props("flat dense no-caps").classes("rounded-xl")
                            elif status_value == "ready_for_review":
                                ui.button(
                                    "Aprovar",
                                    icon="check",
                                    on_click=lambda segment_id=segment.id: (
                                        _approve_continuous_video_segment_from_ui(
                                            project_id,
                                            segment_id,
                                        )
                                    ),
                                ).props("unelevated dense no-caps").classes("acid-bg rounded-xl")
                                ui.button(
                                    "Rejeitar",
                                    icon="close",
                                    on_click=lambda segment_id=segment.id: (
                                        _reject_continuous_video_segment_from_ui(
                                            project_id,
                                            segment_id,
                                        )
                                    ),
                                ).props("flat dense no-caps").classes("rounded-xl")
                                ui.button(
                                    "Regenerar",
                                    icon="refresh",
                                    on_click=lambda segment_id=segment.id: (
                                        _regenerate_continuous_video_segment_from_ui(
                                            project_id,
                                            segment_id,
                                            loading_dialog=continuous_generation_dialog,
                                            progress_callback=continuous_progress_callback,
                                        )
                                    ),
                                ).props("flat dense no-caps").classes("rounded-xl")
                                if generated_video_url and (
                                    not initial_frame_url or not final_frame_url
                                ):
                                    ui.button(
                                        "Extrair frames",
                                        icon="image_search",
                                        on_click=lambda segment_id=segment.id: (
                                            _extract_continuous_video_frames_from_ui(
                                                project_id,
                                                segment_id,
                                                loading_dialog=frame_extraction_dialog,
                                            )
                                        ),
                                    ).props("flat dense no-caps").classes("rounded-xl")
                            elif status_value == "failed":
                                retry_button = ui.button(
                                    "Tentar de novo",
                                    icon="refresh",
                                    on_click=lambda segment_id=segment.id: (
                                        _retry_continuous_video_segment_from_ui(
                                            project_id,
                                            segment_id,
                                            loading_dialog=continuous_generation_dialog,
                                            progress_callback=continuous_progress_callback,
                                        )
                                    ),
                                ).props("unelevated dense no-caps").classes("acid-bg rounded-xl")
                                if not can_use_previous:
                                    retry_button.props("disable")
                                    retry_button.tooltip(
                                        "Aprove o segmento anterior antes de tentar novamente."
                                    )
                            elif status_value == "rejected":
                                regenerate_button = ui.button(
                                    "Regenerar",
                                    icon="refresh",
                                    on_click=lambda segment_id=segment.id: (
                                        _regenerate_rejected_continuous_video_segment_from_ui(
                                            project_id,
                                            segment_id,
                                            loading_dialog=continuous_generation_dialog,
                                            progress_callback=continuous_progress_callback,
                                        )
                                    ),
                                ).props("unelevated dense no-caps").classes("acid-bg rounded-xl")
                                if not can_use_previous:
                                    regenerate_button.props("disable")
                                    regenerate_button.tooltip(
                                        "Aprove o segmento anterior antes de regenerar."
                                    )
                            elif status_value in {"pending", "retry_scheduled"}:
                                generate_button = ui.button(
                                    "Gerar",
                                    icon="play_arrow",
                                    on_click=lambda segment_id=segment.id: (
                                        _generate_continuous_video_segments_from_ui(
                                            project_id,
                                            segment_ids=[segment_id],
                                            retry_failed=False,
                                            max_segments=1,
                                            loading_dialog=continuous_generation_dialog,
                                            progress_callback=continuous_progress_callback,
                                            pause_after_current=pause_after_current,
                                        )
                                    ),
                                ).props("unelevated dense no-caps").classes(
                                    "acid-bg rounded-xl min-w-[104px]"
                                )
                                if not can_use_previous:
                                    generate_button.props("disable")
                                    generate_button.tooltip(
                                        "Aprove o segmento anterior antes de gerar este bloco."
                                    )
                            ui.button(
                                "Editar prompt",
                                icon="edit",
                                on_click=segment_prompt_dialog.open,
                            ).props(
                                "flat dense no-caps"
                                + (" disable" if is_generating_segment else "")
                            ).classes("text-[#d8dbd8] rounded-xl")
        else:
            with ui.element("div").classes("entity-card rounded-2xl p-6 w-full mt-4"):
                ui.label("Nenhum segmento planejado").classes("brand-type text-xl font-bold")
                ui.label(
                    "Crie os blocos a partir do roteiro e da Biblioteca Visual antes de gerar."
                ).classes("text-sm text-[#8d938e] leading-6")

    if not continuous_view_model.is_continuous_mode and pending_frames:
        pending_frame_ids = [frame.id for frame in pending_frames]
        with (
            ui.dialog().props(BLOCKING_DIALOG_PROPS) as video_prompt_dialog,
            ui.card().classes("entity-card rounded-2xl p-6 w-[min(680px,94vw)] max-h-[80vh]"),
        ):
            ui.label("Gerar clipes de vídeo").classes("brand-type text-2xl font-bold")
            ui.label(
                f"Confirme a geração de {len(pending_frames)} clipe(s) a partir dos storyboards aprovados."
            ).classes("text-sm text-[#8d938e]")

            with ui.element("div").classes(
                "border border-[#343934] rounded-xl p-4 mt-4"
            ):
                with ui.row().classes("w-full items-center justify-between gap-3"):
                    with ui.column().classes("gap-1"):
                        ui.label(f"{len(pending_frames)} clipe(s) pendente(s)").classes(
                            "text-sm font-semibold text-[#d8dbd8]"
                        )
                        ui.label(
                            f"Duração total: {pending_duration}s"
                        ).classes("text-xs text-[#8d938e]")
                    ui.badge(f"{pending_duration}s").classes(
                        "blue-status-badge bg-[#243342]"
                    )
                ui.label(_video_cost_text(len(pending_frames), pending_duration)).classes(
                    "text-xs text-[#8d938e] mt-2"
                )

            async def confirm_video_prompts(frame_ids: list[UUID] = pending_frame_ids) -> None:
                safe_close_ui_element(video_prompt_dialog)
                await _approve_video_prompts_from_ui(
                    project_id,
                    frame_ids,
                    loading_dialog=loading_dialog,
                    progress_callback=video_progress_callback,
                )

            with ui.row().classes("w-full justify-end gap-2 mt-6 pt-4 border-t border-[#343934]"):
                ui.button("Cancelar", on_click=video_prompt_dialog.close).props("flat no-caps")
                ui.button(
                    f"Gerar {len(pending_frames)} clipe(s)",
                    icon="check_circle",
                    on_click=confirm_video_prompts,
                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
        with ui.row().classes("w-full items-center justify-end gap-3"):
            review_button = ui.button(
                f"Revisar e gerar ({len(pending_frames)})",
                icon="movie_creation",
                on_click=video_prompt_dialog.open,
            )
            review_button.props("unelevated no-caps").classes("acid-bg rounded-xl")
            if has_active_jobs:
                review_button.props("disable")
        with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
            for frame in pending_frames:
                preview = video_prompt_by_frame_id.get(frame.id, {})
                video_prompt = str(preview.get("prompt") or frame.prompt)
                custom_prompt = bool(preview.get("custom_prompt"))
                image_url = _storyboard_frame_image_url(summary, frame)
                with (
                    ui.dialog().props(BLOCKING_DIALOG_PROPS) as video_prompt_detail_dialog,
                    ui.card().classes(
                        "entity-card rounded-2xl p-6 w-[min(820px,94vw)] "
                        "h-[min(760px,86vh)] flex flex-col overflow-hidden"
                    ),
                ):
                    with ui.column().classes("w-full gap-1 shrink-0"):
                        ui.label(f"Plano {frame.frame_number:02d}").classes(
                            "brand-type text-2xl font-bold"
                        )
                        ui.label(
                            "Prompt customizado"
                            if custom_prompt
                            else "Prompt de vídeo gerado automaticamente"
                        ).classes("text-sm text-[#8d938e]")
                    with ui.column().classes("w-full flex-1 min-h-0 mt-3"):
                        video_prompt_input = (
                            ui.textarea("Prompt de vídeo", value=video_prompt)
                            .props("outlined")
                            .classes("storyboard-prompt-textarea w-full flex-1 min-h-0")
                        )

                    async def save_video_prompt(
                        frame_id: UUID = frame.id,
                        prompt_input: Any = video_prompt_input,
                        dialog: Any = video_prompt_detail_dialog,
                    ) -> None:
                        new_prompt = str(prompt_input.value or "").strip()
                        if not new_prompt:
                            ui.notify("Informe um prompt antes de salvar.", color="warning")
                            return
                        safe_close_ui_element(dialog)
                        await _save_video_prompt_from_ui(project_id, frame_id, new_prompt)

                    async def generate_single_clip(
                        frame_id: UUID = frame.id,
                        prompt_input: Any = video_prompt_input,
                        dialog: Any = video_prompt_detail_dialog,
                    ) -> None:
                        new_prompt = str(prompt_input.value or "").strip()
                        if not new_prompt:
                            ui.notify("Informe um prompt antes de gerar.", color="warning")
                            return
                        safe_close_ui_element(dialog)
                        await _save_video_prompt_from_ui(
                            project_id,
                            frame_id,
                            new_prompt,
                            reload_page=False,
                        )
                        await _approve_video_prompts_from_ui(
                            project_id,
                            [frame_id],
                            loading_dialog=loading_dialog,
                            progress_callback=video_progress_callback,
                        )

                    with ui.row().classes(
                        "w-full justify-end gap-2 mt-4 pt-3 border-t border-[#343934] shrink-0"
                    ):
                        ui.button(
                            "Cancelar",
                            on_click=video_prompt_detail_dialog.close,
                        ).props("flat no-caps")
                        ui.button(
                            "Salvar",
                            icon="save",
                            on_click=save_video_prompt,
                        ).props("flat no-caps").classes("rounded-xl")
                        generate_button = ui.button(
                            "Salvar e gerar clipe",
                            icon="movie_creation",
                            on_click=generate_single_clip,
                        )
                        generate_button.props("unelevated no-caps").classes(
                            "acid-bg rounded-xl"
                        )
                        if frame.id in active_video_frame_ids:
                            generate_button.props("disable")

                with (
                    ui.element("div")
                    .classes("entity-card rounded-2xl overflow-hidden cursor-pointer")
                    .on("click", video_prompt_detail_dialog.open)
                ):
                    with ui.element("div").classes(
                        "storyboard-frame-media visual-placeholder w-full aspect-video p-0 "
                        "relative overflow-hidden bg-black"
                    ):
                        if image_url:
                            ui.image(image_url).classes(
                                "storyboard-frame-image absolute inset-0 w-full h-full object-cover"
                            ).props("fit=cover")
                        else:
                            ui.icon("movie_creation").classes("text-5xl text-[#bdc77b]")
                    with ui.column().classes("p-4 gap-2"):
                        with ui.row().classes("w-full items-center justify-between gap-2"):
                            ui.label(f"Plano {frame.frame_number:02d}").classes("font-semibold")
                            ui.badge("custom" if custom_prompt else "automático").classes(
                                "bg-[#30362b] text-[#eaf878]"
                                if custom_prompt
                                else "blue-status-badge bg-[#243342]"
                            )
                        ui.label(f"{frame.duration_seconds}s").classes("text-xs acid")
                        ui.label(_video_clip_cost_text(frame.duration_seconds)).classes(
                            "text-xs text-[#8d938e]"
                        )
                        ui.label(video_prompt).classes("text-sm text-[#d1d4d1] line-clamp-3")
                        with ui.row().classes("w-full justify-end mt-1"):
                            open_button = (
                                ui.button("Editar prompt", icon="edit")
                                .props("flat dense no-caps")
                                .classes("text-[#d8dbd8] rounded-xl")
                            )
                            open_button.on("click.stop", video_prompt_detail_dialog.open)

    if not continuous_view_model.is_continuous_mode and summary["clips"]:
        with ui.row().classes("w-full items-end justify-between gap-3 mt-6"):
            with ui.column().classes("gap-0"):
                ui.label("Clipes gerados").classes("brand-type text-2xl font-bold")
                ui.label(
                    "Revise os resultados por plano antes de seguir para a finaliza\u00e7\u00e3o."
                ).classes("text-sm text-[#8d938e]")
            ui.badge(f"{generated_count}/{total_frames} criado(s)").classes(
                "bg-[#26301f] text-[#eaf878]"
            )
        with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
            for i, clip in enumerate(summary["clips"], 1):
                frame = frame_by_id.get(clip.storyboard_frame_id)
                preview = video_prompt_by_frame_id.get(clip.storyboard_frame_id, {})
                clip_url = _video_clip_asset_url(clip)
                download_filename = f"storytelling-clipe-{i:02d}.mp4"
                video_prompt = str(
                    preview.get("prompt")
                    or (frame.prompt if frame is not None else "")
                    or "Prompt de vídeo indisponível para este clipe."
                )
                custom_prompt = bool(preview.get("custom_prompt"))
                if clip_url:
                    with (
                        ui.dialog().props("maximized") as video_preview_dialog,
                        ui.card().classes(
                            "entity-card rounded-2xl p-6 w-[min(980px,94vw)] "
                            "max-h-[92vh] flex flex-col overflow-hidden"
                        ),
                    ):
                        with ui.row().classes("w-full items-center justify-between gap-3"):
                            with ui.column().classes("gap-0 min-w-0"):
                                ui.label(f"Clipe {i:02d}").classes("brand-type text-2xl font-bold")
                                ui.label(f"{clip.duration_seconds}s · {clip.model}").classes(
                                    "text-sm text-[#8d938e]"
                                )
                            with ui.row().classes("gap-2 shrink-0"):
                                ui.button(
                                    "Baixar vídeo",
                                    icon="download",
                                    on_click=lambda url=clip_url, filename=download_filename: (
                                        ui.download(
                                            url,
                                            filename,
                                        )
                                    ),
                                ).props("flat no-caps").classes("rounded-xl")
                                ui.button(
                                    "Fechar",
                                    on_click=video_preview_dialog.close,
                                ).props("flat no-caps")
                        with ui.element("div").classes(
                            "w-full flex-1 min-h-0 flex items-center justify-center bg-black rounded-xl overflow-hidden"
                        ):
                            ui.video(clip_url, controls=True).classes(
                                "w-full h-full max-h-[78vh] object-contain"
                            )
                if frame is not None:
                    with (
                        ui.dialog().props(BLOCKING_DIALOG_PROPS) as clip_prompt_dialog,
                        ui.card().classes(
                            "entity-card rounded-2xl p-6 w-[min(820px,94vw)] "
                            "h-[min(760px,86vh)] flex flex-col overflow-hidden"
                        ),
                    ):
                        with ui.column().classes("w-full gap-1 shrink-0"):
                            ui.label(f"Clipe {i:02d}").classes("brand-type text-2xl font-bold")
                            ui.label(
                                "Edite o prompt e gere uma nova variação para este plano."
                            ).classes("text-sm text-[#8d938e]")
                        with ui.column().classes("w-full flex-1 min-h-0 mt-3"):
                            clip_prompt_input = (
                                ui.textarea("Prompt de vídeo", value=video_prompt)
                                .props("outlined")
                                .classes("storyboard-prompt-textarea w-full flex-1 min-h-0")
                            )

                        async def save_clip_prompt(
                            frame_id: UUID = clip.storyboard_frame_id,
                            prompt_input: Any = clip_prompt_input,
                            dialog: Any = clip_prompt_dialog,
                        ) -> None:
                            new_prompt = str(prompt_input.value or "").strip()
                            if not new_prompt:
                                ui.notify("Informe um prompt antes de salvar.", color="warning")
                                return
                            safe_close_ui_element(dialog)
                            await _save_video_prompt_from_ui(project_id, frame_id, new_prompt)

                        async def generate_clip_variation(
                            frame_id: UUID = clip.storyboard_frame_id,
                            prompt_input: Any = clip_prompt_input,
                            dialog: Any = clip_prompt_dialog,
                        ) -> None:
                            new_prompt = str(prompt_input.value or "").strip()
                            if not new_prompt:
                                ui.notify("Informe um prompt antes de gerar.", color="warning")
                                return
                            safe_close_ui_element(dialog)
                            await _save_video_prompt_from_ui(
                                project_id,
                                frame_id,
                                new_prompt,
                                reload_page=False,
                            )
                            await _approve_video_prompts_from_ui(
                                project_id,
                                [frame_id],
                                loading_dialog=loading_dialog,
                                progress_callback=video_progress_callback,
                            )

                        with ui.row().classes(
                            "w-full justify-end gap-2 mt-4 pt-3 border-t border-[#343934] shrink-0"
                        ):
                            ui.button("Cancelar", on_click=clip_prompt_dialog.close).props(
                                "flat no-caps"
                            )
                            ui.button(
                                "Salvar",
                                icon="save",
                                on_click=save_clip_prompt,
                            ).props("flat no-caps").classes("rounded-xl")
                            ui.button(
                                "Salvar e gerar variação",
                                icon="movie_creation",
                                on_click=generate_clip_variation,
                            ).props("unelevated no-caps").classes("acid-bg rounded-xl")

                with ui.element("div").classes("entity-card rounded-2xl overflow-hidden"):
                    with ui.element("div").classes(
                        "visual-placeholder aspect-video flex items-center justify-center relative bg-black overflow-hidden"
                    ):
                        if clip_url:
                            ui.video(clip_url, controls=True).classes(
                                "w-full h-full object-contain"
                            )
                        else:
                            ui.button(icon="play_arrow").props("round unelevated").classes(
                                "acid-bg"
                            )
                    with ui.column().classes("p-4 gap-2"):
                        with ui.row().classes("w-full justify-between"):
                            ui.label(f"Clipe {i:02d}").classes("font-semibold")
                            ui.badge(
                                "Selecionado" if clip.selected else "Varia\u00e7\u00e3o"
                            ).classes("bg-[#30362b] text-[#eaf878]")
                        ui.label(f"{clip.duration_seconds}s \u00b7 {clip.model}").classes(
                            "text-xs text-[#878d88]"
                        )
                        ui.label(
                            _video_clip_cost_text(clip.duration_seconds, str(clip.model or ""))
                        ).classes("text-xs text-[#8d938e]")
                        ui.label(video_prompt).classes("text-sm text-[#d1d4d1] line-clamp-3")
                        if frame is not None or clip_url:
                            with ui.row().classes("w-full items-center justify-between gap-2"):
                                if frame is not None:
                                    ui.badge("custom" if custom_prompt else "automático").classes(
                                        "bg-[#30362b] text-[#eaf878]"
                                        if custom_prompt
                                        else "blue-status-badge bg-[#243342]"
                                    )
                                else:
                                    ui.space()
                                with ui.row().classes("gap-1"):
                                    if clip_url:
                                        ui.button(
                                            "Visualizar",
                                            icon="play_arrow",
                                            on_click=video_preview_dialog.open,
                                        ).props("flat dense no-caps").classes(
                                            "text-[#d8dbd8] rounded-xl"
                                        )
                                        ui.button(
                                            "Baixar",
                                            icon="download",
                                            on_click=lambda url=clip_url, filename=download_filename: (
                                                ui.download(
                                                    url,
                                                    filename,
                                                )
                                            ),
                                        ).props("flat dense no-caps").classes(
                                            "text-[#d8dbd8] rounded-xl"
                                        )
                                    if frame is not None:
                                        ui.button(
                                            "Editar prompt",
                                            icon="edit",
                                            on_click=clip_prompt_dialog.open,
                                        ).props("flat dense no-caps").classes(
                                            "text-[#d8dbd8] rounded-xl"
                                        )
    elif not continuous_view_model.is_continuous_mode and not pending_frames:
        with ui.element("div").classes("entity-card rounded-2xl p-6 w-full mt-4"):
            ui.label("Nenhum clipe para gerar ainda").classes("brand-type text-2xl font-bold")
            ui.label(
                "Quando o storyboard estiver pronto, está tela mostrar\u00e1 os planos "
                "que podem virar clipes."
            ).classes("text-sm text-[#8d938e] leading-6")

    if not continuous_view_model.is_continuous_mode and summary["clips"]:
        with ui.row().classes("w-full items-center justify-between gap-3 mt-6"):
            with ui.column().classes("gap-0"):
                ui.label("Montagem").classes("brand-type text-2xl font-bold")
                ui.label(
                    f"Previs\u00e3o de dura\u00e7\u00e3o: {total_duration}s"
                    if total_duration
                    else "A timeline organiza os clipes na ordem dos planos."
                ).classes("text-sm text-[#8d938e]")
            if timeline is None:
                ui.badge("timeline pendente").classes("blue-status-badge bg-[#243342]")
        _render_timeline_strip(timeline, summary["timeline_items"])


def render_finalization_area(
    project_id: UUID,
    summary: dict[str, Any],
    *,
    section_title: SectionTitle,
    loading_dialog_factory: LoadingDialogFactory | None = None,
) -> None:
    del loading_dialog_factory
    continuous_view_model = build_continuous_video_view_model(summary)
    clips = list(summary.get("clips", []))
    approved_continuous_segments = [
        segment
        for segment in summary.get("continuous_video_segments", [])
        if str(getattr(segment, "review_status", "") or "").lower() == "approved"
    ]
    timeline = summary.get("timeline")
    timeline_items = list(summary.get("timeline_items", []))
    export = summary.get("export")
    export_status = str(getattr(export, "status", "") or "").upper()
    manifest_only = export is not None and export_status == "MANIFEST_ONLY"
    export_url = _export_asset_url(export) if export is not None else ""
    export_filename = _export_filename(export) if export is not None else "storytelling-final.mp4"
    clip_duration = sum(int(getattr(clip, "duration_seconds", 0) or 0) for clip in clips)
    continuous_duration = sum(
        int(getattr(segment, "duration_seconds", 0) or 0)
        for segment in approved_continuous_segments
    )
    timeline_duration = int(getattr(timeline, "duration_seconds", 0) or 0)
    total_duration = timeline_duration or continuous_duration or clip_duration
    section_title(
        "Finalização",
        "Monte a timeline final, gere o arquivo único e prepare o projeto para entrega.",
        None,
        None,
    )
    if not clips and not approved_continuous_segments:
        with ui.element("div").classes("entity-card rounded-2xl p-6 w-full"):
            ui.label("Nenhum video pronto para finalizar").classes("brand-type text-2xl font-bold")
            ui.label("Gere os clipes na etapa de vídeo antes de montar a timeline final.").classes(
                "text-sm text-[#8d938e] leading-6"
            )
        return

    finalization_loading_dialog, _finalization_progress_callback = generation_progress_dialog(
        "Finalizando projeto",
        1,
        "export",
        loading_status_message(
            "finalization",
            summary["counts"],
            now="Agora: montando a timeline final e gerando o arquivo unico.",
        ),
    )
    progress_value = 1.0 if export is not None else (0.5 if timeline is not None else 0.0)
    with ui.element("div").classes("w-full entity-card rounded-2xl p-5"):
        with ui.row().classes("w-full items-start justify-between gap-3"):
            with ui.column().classes("gap-1 min-w-0"):
                ui.label("Timeline e export final").classes("brand-type text-2xl font-bold")
                timeline_copy = (
                    "Une os segmentos continuos aprovados e cria um unico arquivo."
                    if continuous_view_model.is_continuous_mode
                    else "Une os clipes selecionados em ordem de storyboard e cria um unico arquivo."
                )
                ui.label(timeline_copy).classes("text-sm text-[#8d938e]")
                ui.label(
                    "Custo de IA previsto: US$ 0.000000. Esta etapa usa processamento local."
                ).classes("text-xs text-[#8d938e]")
            ui.badge(
                "manifest sem vídeo"
                if manifest_only
                else (
                    export_status
                    or ("timeline pronta" if timeline is not None else "pendente")
                )
            ).classes(
                "bg-[#4b2a2a] text-[#ffd4d4]"
                if manifest_only
                else (
                    "bg-[#26301f] text-white"
                    if export_status == "RENDERED"
                    else "blue-status-badge bg-[#243342]"
                )
            )
        ui.linear_progress(value=progress_value, show_value=False).classes("w-full mt-3").props(
            "instant-feedback rounded"
        )
        with ui.row().classes("w-full items-center justify-between gap-3 mt-3"):
            timeline_stats = (
                f"{len(approved_continuous_segments)} segmento(s) aprovado(s) · "
                f"{total_duration}s · saida 720p"
                if continuous_view_model.is_continuous_mode
                else f"{len(clips)} clipe(s) selecionado(s) · {total_duration}s · saida 720p"
            )
            ui.label(timeline_stats).classes("text-xs text-[#8d938e]")
            with ui.row().classes("gap-2"):
                if export_url:
                    ui.button(
                        "Baixar manifest (JSON)" if manifest_only else "Baixar final",
                        icon="download",
                        on_click=lambda url=export_url, filename=export_filename: ui.download(
                            url,
                            filename,
                        ),
                    ).props("flat no-caps").classes("rounded-xl")
                ui.button(
                    "Gerar final" if export is None else "Gerar novamente",
                    icon="auto_awesome_motion",
                    on_click=lambda: _enqueue_finalization_from_ui(
                        project_id,
                        loading_dialog=finalization_loading_dialog,
                    ),
                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
        if export is not None:
            ui.label(f"Arquivo: {getattr(export, 'output_uri', '')}").classes(
                "text-xs text-[#8d938e] mt-2 break-all"
            )
            if manifest_only:
                with ui.element("div").classes(
                    "border border-red-900 bg-red-950/40 rounded-xl px-4 py-3 mt-3"
                ):
                    ui.label(
                        "Exportação incompleta: nenhum vídeo foi gerado. "
                        "O arquivo disponível é um manifest JSON com os metadados da montagem."
                    ).classes("text-sm font-semibold text-red-100")
                    ui.label(
                        "O FFmpeg não produziu o MP4 final. Verifique o motivo abaixo, "
                        "corrija o ambiente e gere novamente."
                    ).classes("text-xs text-red-200/80 mt-1")
            render_log = str(getattr(export, "render_log", "") or "").strip()
            if render_log:
                ui.label(render_log[:420]).classes("text-xs text-[#8d938e] mt-1")

    _render_timeline_strip(timeline, timeline_items)


def render_dubbing_area(
    project_id: UUID,
    summary: dict[str, Any],
    *,
    section_title: SectionTitle,
    loading_dialog_factory: LoadingDialogFactory | None = None,
) -> None:
    del loading_dialog_factory
    clips = list(summary.get("clips", []))
    total_duration = sum(int(getattr(clip, "duration_seconds", 0) or 0) for clip in clips)
    section_title(
        "Dublagem",
        "Gere a versão dublada do vídeo final usando ElevenLabs.",
        None,
        None,
    )
    if not clips:
        with ui.element("div").classes("entity-card rounded-2xl p-6 w-full"):
            ui.label("Nenhum clipe pronto para dublar").classes("brand-type text-2xl font-bold")
            ui.label("Gere os clipes na etapa de vídeo antes de criar a dublagem.").classes(
                "text-sm text-[#8d938e] leading-6"
            )
        return

    dubbing_job = summary.get("dubbing_job")
    dubbing_status = str(getattr(dubbing_job, "status", "") or "").upper()
    dubbing_progress = int(getattr(dubbing_job, "progress", 0) or 0)
    dubbing_target = str(
        getattr(dubbing_job, "target_language", "") or get_settings().dubbing_target_lang
    )
    dubbing_url = _dubbing_asset_url(dubbing_job) if dubbing_job is not None else ""
    dubbing_loading_dialog, _dubbing_progress_callback = generation_progress_dialog(
        "Preparando dublagem",
        1,
        "job",
        loading_status_message(
            "dubbing",
            summary["counts"],
            now="Agora: preparando o export base e acionando o ElevenLabs.",
        ),
    )
    with ui.element("div").classes("w-full entity-card rounded-2xl p-5"):
        with ui.row().classes("w-full items-start justify-between gap-3"):
            with ui.column().classes("gap-1 min-w-0"):
                ui.label("Dublagem ElevenLabs").classes("brand-type text-2xl font-bold")
                ui.label(
                    "Cria um export base 720p com os clipes selecionados e envia para dublagem."
                ).classes("text-sm text-[#8d938e]")
                ui.label(_dubbing_cost_text(total_duration)).classes("text-xs text-[#8d938e]")
            ui.badge(dubbing_status or "pendente").classes(
                "bg-[#26301f] text-white"
                if dubbing_status == "SUCCEEDED"
                else "blue-status-badge bg-[#243342]"
            )
        ui.linear_progress(
            value=_progress_ratio(dubbing_progress, 100),
            show_value=False,
        ).classes("w-full mt-3").props("instant-feedback rounded")
        with ui.row().classes("w-full items-center justify-between gap-3 mt-3"):
            ui.label(
                f"{len(clips)} clipe(s) · {total_duration}s · idioma alvo: "
                f"{dubbing_target or 'não configurado'}"
            ).classes("text-xs text-[#8d938e]")
            with ui.row().classes("gap-2"):
                if dubbing_job is not None and dubbing_status not in {"SUCCEEDED", "FAILED"}:
                    ui.button(
                        "Atualizar status",
                        icon="sync",
                        on_click=lambda job_id=dubbing_job.id: _refresh_dubbing_from_ui(
                            project_id,
                            job_id,
                            loading_dialog=dubbing_loading_dialog,
                        ),
                    ).props("flat no-caps").classes("rounded-xl")
                if dubbing_url:
                    ui.button(
                        "Baixar dublagem",
                        icon="download",
                        on_click=lambda url=dubbing_url: ui.download(
                            url,
                            f"storytelling-dublagem-{dubbing_target or 'audio'}.mp4",
                        ),
                    ).props("flat no-caps").classes("rounded-xl")
                ui.button(
                    "Gerar dublagem" if dubbing_job is None else "Reaproveitar/atualizar",
                    icon="graphic_eq",
                    on_click=lambda: _enqueue_dubbing_from_ui(
                        project_id,
                        loading_dialog=dubbing_loading_dialog,
                    ),
                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
        if dubbing_job is not None and getattr(dubbing_job, "error", None):
            ui.label(str(dubbing_job.error)).classes("text-xs text-red-300 mt-2")
