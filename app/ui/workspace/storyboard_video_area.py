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
from app.ui.workspace import storyboard_handlers as _storyboard_handlers
from app.ui.workspace.continuous_video_view_model import (
    CONTINUOUS_VIDEO_WORKFLOW_MODE,
    build_continuous_video_view_model,
    continuous_video_status_label,
)
from app.video_generation.continuous import (
    CONTINUOUS_VIDEO_FLOW_URL,
    approve_continuous_video_segment,
    continuous_video_segment_validation_errors,
    plan_continuous_video_segments,
    prepare_continuous_video_flow_package,
    reject_continuous_video_segment,
    update_continuous_video_segment_prompt,
)

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


def _normalize_video_workflow_mode_from_ui(_value: object) -> str:
    # O modo de producao e unico: sempre o assistente Google Flow (continuous_fast).
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


async def _prepare_continuous_video_flow_package_from_ui(
    project_id: UUID,
    *,
    segment_ids: list[UUID] | None = None,
    loading_dialog: Any | None = None,
) -> None:
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            segments, validation_errors = await prepare_continuous_video_flow_package(
                session,
                project_id,
                segment_ids=segment_ids,
            )
        failed = [
            segment
            for segment in segments
            if str(getattr(segment, "review_status", "") or "").lower() == "failed"
        ]
        if failed:
            metadata = (
                failed[0].metadata_json if isinstance(failed[0].metadata_json, dict) else {}
            )
            message = str(metadata.get("error") or "N\u00e3o foi poss\u00edvel preparar o pacote.")
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
                "Pacote para o Google Flow pronto!",
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
        _safe_notify("Segmento conclu\u00eddo. O pr\u00f3ximo bloco j\u00e1 pode continuar daqui.", color="positive")
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
        _safe_notify("Segmento marcado para refazer. O pacote ser\u00e1 preparado novamente.", color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


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
    continuous_segments = list(summary.get("continuous_video_segments", []))
    segment_total_duration = sum(
        int(getattr(segment, "duration_seconds", 0) or 0) for segment in continuous_segments
    )
    segment_plan_dialog, _segment_plan_progress_callback = generation_progress_dialog(
        "Planejando segmentos",
        1,
        "etapa",
        "Agora: separando o roteiro em blocos para o Google Flow.",
    )
    prepare_dialog, _prepare_progress_callback = generation_progress_dialog(
        "Preparando pacote",
        1,
        "segmento",
        "Agora: gerando o frame final de cada segmento com o modelo de imagem.",
    )

    with ui.row().classes("w-full items-start justify-between gap-4 mb-2"):
        with ui.column().classes("gap-1 min-w-0"):
            ui.label("Produ\u00e7\u00e3o de v\u00eddeo").classes("brand-type text-3xl font-bold")
            ui.label(
                "Assistente de produ\u00e7\u00e3o: prepare o pacote e crie o v\u00eddeo no Google Flow "
                "(flow.google.com) com o prompt, o frame inicial e o frame final de cada segmento."
            ).classes("text-sm text-[#8e948f]")
        with ui.column().classes("items-end gap-2 shrink-0"):
            ui.button(
                "Replanejar" if continuous_segments else "Planejar segmentos",
                icon="view_timeline",
                on_click=lambda: _plan_continuous_video_segments_from_ui(
                    project_id,
                    loading_dialog=segment_plan_dialog,
                ),
            ).props("flat no-caps").classes("rounded-xl")
            ui.button(
                "Preparar pacote",
                icon="auto_awesome",
                on_click=lambda: _prepare_continuous_video_flow_package_from_ui(
                    project_id,
                    loading_dialog=prepare_dialog,
                ),
            ).props("unelevated no-caps").classes("acid-bg rounded-xl")
            if continuous_segments:
                ui.label(
                    f"{len(continuous_segments)} segmento(s) \u00b7 {segment_total_duration}s total"
                ).classes("text-xs text-[#8d938e]")
            ui.link(
                "Abrir Google Flow",
                CONTINUOUS_VIDEO_FLOW_URL,
                new_tab=True,
            ).classes("text-xs acid")

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
                    if continuous_view_model.can_conclude:
                        ui.badge("pacote pronto para concluir").classes(
                            "blue-status-badge bg-[#26301f]"
                        )

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
                    is_preparing_segment = status_value in {
                        "preparing",
                        "generating",
                        "running",
                        "sending",
                        "processing",
                    }
                    initial_frame_url = _asset_content_url(
                        metadata.get("initial_frame_asset_id")
                        or getattr(segment, "source_frame_asset_id", None)
                    )
                    final_frame_url = _asset_content_url(
                        getattr(segment, "final_frame_asset_id", None)
                        or metadata.get("final_frame_asset_id")
                    )
                    flow_url = str(metadata.get("flow_url") or CONTINUOUS_VIDEO_FLOW_URL)
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
                                f"\u00b7 Prompt para o Google Flow"
                            ).classes("text-sm text-[#8d938e]")
                        with ui.column().classes("w-full flex-1 min-h-0 mt-3"):
                            segment_prompt_input = (
                                ui.textarea(
                                    "Prompt para o Google Flow",
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
                                ui.label("Frame inicial e frame final").classes(
                                    "text-xs text-[#8d938e]"
                                )
                            ui.button(
                                icon="close",
                                on_click=segment_media_dialog.close,
                            ).props("flat round dense")
                        with ui.grid().classes(
                            "w-full grid-cols-1 lg:grid-cols-2 gap-4 mt-4 flex-1 min-h-0 overflow-y-auto"
                        ):
                            _render_continuous_media_preview(
                                "Frame inicial",
                                initial_frame_url,
                                media_kind="image",
                                large=True,
                            )
                            _render_continuous_media_preview(
                                "Frame final",
                                final_frame_url,
                                media_kind="image",
                                large=True,
                            )

                    with ui.element("div").classes("entity-card rounded-2xl p-4"):
                        with ui.row().classes("w-full items-start justify-between gap-3"):
                            with ui.column().classes("gap-1 min-w-0"):
                                ui.label(
                                    getattr(segment, "title", "")
                                    or f"Segmento {segment.segment_number:02d}"
                                ).classes("font-semibold")
                                ui.label(
                                    f"{int(getattr(segment, 'duration_seconds', 0) or 0)}s "
                                    f"\u00b7 {continuous_video_status_label(status_value)}"
                                ).classes("text-xs text-[#8d938e]")
                            ui.badge(continuous_video_status_label(status_value) or "pendente").classes(
                                "bg-[#26301f] text-[#eaf878]"
                                if status_value in {"done", "approved", "ready", "ready_for_review", "succeeded"}
                                else (
                                    "bg-[#4b2a2a] text-[#ffd4d4]"
                                    if status_value in {"failed", "rejected"}
                                    else "blue-status-badge bg-[#243342]"
                                )
                            )
                        if initial_frame_url or final_frame_url:
                            with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 gap-3 mt-3"):
                                _render_continuous_media_preview(
                                    "Frame inicial",
                                    initial_frame_url,
                                    media_kind="image",
                                )
                                _render_continuous_media_preview(
                                    "Frame final",
                                    final_frame_url,
                                    media_kind="image",
                                )
                        if metadata.get("error"):
                            ui.label(str(metadata.get("error"))[:240]).classes(
                                "text-xs text-[#ffb4b4] mt-2"
                            )
                        if validation_errors:
                            ui.label("; ".join(validation_errors)).classes(
                                "text-xs text-[#ffb4b4] mt-2"
                            )
                        if is_preparing_segment:
                            with ui.row().classes(
                                "items-center gap-2 mt-3 text-sm text-[#d1d4d1]"
                            ):
                                ui.spinner(size="sm").classes("acid")
                                ui.label(
                                    "Preparando o pacote (gerando o frame final). Atualize para verificar."
                                )
                        ui.label(str(metadata.get("action") or "")).classes(
                            "text-sm text-[#d1d4d1] line-clamp-3 mt-3"
                        )
                        if visual_summary:
                            ui.label(visual_summary).classes("text-xs text-[#8d938e] mt-2")
                        ui.label(str(getattr(segment, "prompt", "") or "")).classes(
                            "text-xs text-[#aeb4af] whitespace-pre-wrap mt-3 line-clamp-5"
                        )
                        with ui.row().classes("w-full flex-wrap justify-end gap-2 mt-2"):
                            if initial_frame_url or final_frame_url:
                                ui.button(
                                    "Visualizar",
                                    icon="open_in_full",
                                    on_click=segment_media_dialog.open,
                                ).props("flat dense no-caps").classes("rounded-xl")
                            if status_value in {"pending", "retry_scheduled", "failed", "rejected"}:
                                ui.button(
                                    "Preparar",
                                    icon="auto_awesome",
                                    on_click=lambda segment_id=segment.id: (
                                        _prepare_continuous_video_flow_package_from_ui(
                                            project_id,
                                            segment_ids=[segment_id],
                                            loading_dialog=prepare_dialog,
                                        )
                                    ),
                                ).props("unelevated dense no-caps").classes(
                                    "acid-bg rounded-xl min-w-[104px]"
                                )
                            if status_value in {"ready", "ready_for_review"}:
                                ui.button(
                                    "Concluir",
                                    icon="check",
                                    on_click=lambda segment_id=segment.id: (
                                        _approve_continuous_video_segment_from_ui(
                                            project_id,
                                            segment_id,
                                        )
                                    ),
                                ).props("unelevated dense no-caps").classes("acid-bg rounded-xl")
                                ui.button(
                                    "Refazer",
                                    icon="close",
                                    on_click=lambda segment_id=segment.id: (
                                        _reject_continuous_video_segment_from_ui(
                                            project_id,
                                            segment_id,
                                        )
                                    ),
                                ).props("flat dense no-caps").classes("rounded-xl")
                            if status_value == "done":
                                ui.button(
                                    "Refazer",
                                    icon="undo",
                                    on_click=lambda segment_id=segment.id: (
                                        _reject_continuous_video_segment_from_ui(
                                            project_id,
                                            segment_id,
                                        )
                                    ),
                                ).props("flat dense no-caps").classes("rounded-xl")
                            ui.link(
                                "Abrir Google Flow",
                                flow_url,
                                new_tab=True,
                            ).classes("text-xs acid self-center")
                            ui.button(
                                "Copiar prompt",
                                icon="content_copy",
                                on_click=lambda prompt=segment.prompt: _copy_text_to_clipboard(
                                    prompt
                                ),
                            ).props("flat dense no-caps").classes("text-[#d8dbd8] rounded-xl")
                            ui.button(
                                "Editar prompt",
                                icon="edit",
                                on_click=segment_prompt_dialog.open,
                            ).props(
                                "flat dense no-caps"
                                + (" disable" if is_preparing_segment else "")
                            ).classes("text-[#d8dbd8] rounded-xl")
        else:
            with ui.element("div").classes("entity-card rounded-2xl p-6 w-full mt-4"):
                ui.label("Nenhum segmento planejado").classes("brand-type text-xl font-bold")
                ui.label(
                    "Planeje os segmentos a partir do roteiro e da Biblioteca Visual antes de preparar o pacote."
                ).classes("text-sm text-[#8d938e] leading-6")

    if summary["clips"]:
        with ui.row().classes("w-full items-end justify-between gap-3 mt-6"):
            with ui.column().classes("gap-0"):
                ui.label("Clipes legados").classes("brand-type text-2xl font-bold")
                ui.label(
                    "Hist\u00f3rico de clipes gerados antes da transi\u00e7\u00e3o para o Google Flow."
                ).classes("text-sm text-[#8d938e]")
            ui.badge(f"{len(summary['clips'])} clipe(s)").classes(
                "blue-status-badge bg-[#243342]"
            )
        with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
            for i, clip in enumerate(summary["clips"], 1):
                clip_url = _video_clip_asset_url(clip)
                with ui.element("div").classes("entity-card rounded-2xl overflow-hidden"):
                    with ui.element("div").classes(
                        "visual-placeholder aspect-video flex items-center justify-center relative bg-black overflow-hidden"
                    ):
                        if clip_url:
                            ui.video(clip_url, controls=True).classes(
                                "w-full h-full object-contain"
                            )
                        else:
                            ui.icon("movie_creation").classes("text-5xl text-[#bdc77b]")
                    with ui.column().classes("p-4 gap-2"):
                        with ui.row().classes("w-full justify-between"):
                            ui.label(f"Clipe {i:02d}").classes("font-semibold")
                            ui.badge(
                                "Selecionado" if clip.selected else "Varia\u00e7\u00e3o"
                            ).classes("bg-[#30362b] text-[#eaf878]")
                        ui.label(f"{clip.duration_seconds}s \u00b7 {clip.model}").classes(
                            "text-xs text-[#878d88]"
                        )
