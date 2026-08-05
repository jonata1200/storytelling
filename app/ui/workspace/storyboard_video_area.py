# ruff: noqa: E501

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
from app.storyboards.service import (
    approve_storyboard_prompt,
    approve_storyboard_prompts,
    generate_animatic_bundle,
    generate_storyboard_frames,
    storyboard_frames_need_generation,
    storyboard_prompts_need_approval,
    update_storyboard_prompt,
)
from app.ui.shared.generation_progress import generation_progress_dialog, progress_ratio
from app.ui.shared.page_config import BLOCKING_DIALOG_PROPS, friendly_ai_error, show_ai_error_popup
from app.ui.visual.actions import _approve_video_prompts_from_ui
from app.ui.visual.helpers import asset_url
from app.ui.workspace import storyboard_handlers as _storyboard_handlers
from app.ui.workspace.panels import _render_timeline_strip
from app.ui.workspace.storyboard_video_view_model import build_storyboard_video_view_model
from app.ui.workspace.video_handlers import save_video_prompt_from_ui as _save_video_prompt_from_ui

SectionTitle = Callable[[str, str, str | None, Any | None], None]
LoadingDialogFactory = Callable[[str, str], Any]


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


async def _enqueue_dubbing_from_ui(
    project_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    if loading_dialog is not None:
        loading_dialog.open()
    try:
        async with AsyncSessionLocal() as session:
            job = await enqueue_project_step(session, project_id, "dubbing")
        ui.notify(f"Dublagem enfileirada: {job.id}.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        if loading_dialog is not None:
            loading_dialog.close()


async def _refresh_dubbing_from_ui(
    project_id: UUID,
    job_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    if loading_dialog is not None:
        loading_dialog.open()
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
            loading_dialog.close()


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


def _dubbing_asset_url(job: Any) -> str:
    asset_id = getattr(job, "result_asset_id", None)
    if asset_id is None:
        return ""
    return f"/api/v1/assets/{asset_id}/content"


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
                "bg-[#26301f] text-[#eaf878]"
                if missing == 0 and total
                else "blue-status-badge bg-[#243342]"
            )
        ui.linear_progress(value=_progress_ratio(generated, total)).classes(
            "w-full mt-3"
        ).props("instant-feedback rounded")


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
        model="veo-3.1-fast-generate-preview",
    )
    return f"Estimativa: US$ {estimate.estimated} para {frame_count} clipe(s)."


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
        "A IA está criando os quadros aprovados do storyboard.",
    )
    prompt_dialog: Any | None = None
    if script_id is not None and prompt_previews:
        active_script_id: UUID = script_id
        with (
            ui.dialog().props(BLOCKING_DIALOG_PROPS) as prompt_dialog,
            ui.card().classes("entity-card rounded-2xl p-6 w-[min(920px,94vw)] max-h-[86vh]"),
        ):
            ui.label("Aprovar prompts de storyboard").classes("brand-type text-2xl font-bold")
            ui.label(
                "Revise os prompts por cena e plano antes de liberar a geração das imagens."
            ).classes("text-sm text-[#8d938e]")
            ui.label(
                f"Agora: gerar {len(missing_frame_previews)} e reaproveitar {storyboard_generated}."
            ).classes("text-xs text-[#8d938e]")
            with ui.scroll_area().classes("w-full max-h-[58vh] pr-2"):
                with ui.column().classes("w-full gap-3"):
                    for preview in prompt_previews:
                        approved = bool(preview.get("approved"))
                        with ui.element("div").classes("border border-[#343934] rounded-xl p-4"):
                            with ui.row().classes("w-full items-center justify-between gap-3"):
                                ui.label(
                                    "Cena "
                                    f"{int(preview.get('scene_number') or 0):02d} · "
                                    f"Plano {int(preview.get('shot_number') or 0):02d} · "
                                    f"{int(preview.get('duration_seconds') or 0)}s"
                                ).classes("text-sm font-semibold")
                                ui.badge("aprovado" if approved else "pendente").classes(
                                    "bg-[#26301f] text-white" if approved else "bg-[#5aa3f0]"
                                )
                            ui.label(str(preview.get("prompt") or "")).classes(
                                "text-xs text-[#aeb4af] whitespace-pre-wrap mt-2"
                            )
                            _render_continuity_checks(
                                list(preview.get("continuity_checks") or [])
                            )

            async def confirm_storyboard_prompts() -> None:
                prompt_dialog.close()
                await _approve_storyboard_prompts_from_ui(
                    project_id,
                    script_id,
                    loading_dialog=generation_dialog,
                    progress_callback=storyboard_progress_callback,
                )

            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Fechar", on_click=prompt_dialog.close).props("flat no-caps")
                if pending_prompt_previews:
                    ui.button(
                        "Aprovar prompts e gerar",
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
                            dialog.close()
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
                        ).props("unelevated dense no-caps").classes(
                            "acid-bg self-start rounded-xl"
                        )
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
    section_title(
        "Produ\u00e7\u00e3o de v\u00eddeo",
        "Transforme cada quadro aprovado em clipes e acompanhe a montagem final.",
        None,
        None,
    )
    view_model = build_storyboard_video_view_model(summary)
    pending_frames = view_model.pending_frames
    video_prompt_by_frame_id = view_model.video_prompt_by_frame_id
    frame_by_id = view_model.frame_by_id
    generated_count = view_model.generated_count
    total_frames = view_model.total_frames
    active_video_job_count = view_model.queued_video_jobs + view_model.running_video_jobs
    timeline = summary["timeline"]
    total_duration = view_model.total_duration
    loading_dialog, video_progress_callback = generation_progress_dialog(
        "Gerando clipes",
        len(pending_frames),
        "clipe",
        "A IA está enviando os clipes aprovados para a fila de vídeo.",
    )
    video_missing = max(total_frames - generated_count, 0)
    pending_duration = sum(
        int(getattr(frame, "duration_seconds", 0) or 0) for frame in pending_frames
    )
    if total_frames:
        video_detail = "Saída padronizada em 720p."
        if active_video_job_count:
            video_detail = (
                f"{active_video_job_count} job(s) em fila/processando. "
                "Saída padronizada em 720p."
            )
        if view_model.failed_video_jobs:
            video_detail = (
                f"{video_detail} {view_model.failed_video_jobs} job(s) com falha recente."
            )
        _render_generation_progress_summary(
            "Clipes de vídeo",
            generated_count,
            total_frames,
            video_missing,
            f"{video_detail} {_video_cost_text(len(pending_frames), pending_duration)}",
            badge="720p",
        )

    if summary["clips"]:
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
            "A aplicação está preparando o export base e acionando o ElevenLabs.",
        )
        with ui.element("div").classes("w-full entity-card rounded-2xl p-4 mb-3"):
            with ui.row().classes("w-full items-start justify-between gap-3"):
                with ui.column().classes("gap-1 min-w-0"):
                    ui.label("Dublagem").classes("brand-type text-2xl font-bold")
                    ui.label(
                        "Etapa após os clipes: cria um export base 720p e envia ao ElevenLabs."
                    ).classes("text-sm text-[#8d938e]")
                    ui.label(_dubbing_cost_text(total_duration)).classes(
                        "text-xs text-[#8d938e]"
                    )
                ui.badge(dubbing_status or "pendente").classes(
                    "bg-[#26301f] text-[#eaf878]"
                    if dubbing_status == "SUCCEEDED"
                    else "blue-status-badge bg-[#243342]"
                )
            ui.linear_progress(value=_progress_ratio(dubbing_progress, 100)).classes(
                "w-full mt-3"
            ).props("instant-feedback rounded")
            with ui.row().classes("w-full items-center justify-between gap-3 mt-3"):
                ui.label(f"Idioma alvo: {dubbing_target or 'não configurado'}").classes(
                    "text-xs text-[#8d938e]"
                )
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

    if pending_frames:
        pending_frame_ids = [frame.id for frame in pending_frames]
        with (
            ui.dialog().props(BLOCKING_DIALOG_PROPS) as video_prompt_dialog,
            ui.card().classes(
                "entity-card rounded-2xl p-6 w-[min(920px,94vw)] max-h-[86vh]"
            ),
        ):
            ui.label("Revisar prompts e gerar clipes").classes("brand-type text-2xl font-bold")
            ui.label(
                "Confira os planos que ainda n\u00e3o possuem v\u00eddeo. Ao confirmar, "
                "a IA gera um clipe para cada plano listado."
            ).classes("text-sm text-[#8d938e]")
            ui.label(
                f"Agora: gerar {len(pending_frames)} e reaproveitar {generated_count}."
            ).classes("text-xs text-[#8d938e]")
            ui.label(_video_cost_text(len(pending_frames), pending_duration)).classes(
                "text-xs text-[#8d938e]"
            )
            high_consistency_toggle = ui.checkbox(
                "Alta consistência visual",
                value=False,
            ).props("dense")
            ui.label(
                "Usa referências canônicas extras somente em planos de 8s; deixe desligado "
                "para o fluxo mais barato e rápido."
            ).classes("text-xs text-[#8d938e]")
            with ui.scroll_area().classes("w-full max-h-[52vh] pr-2"):
                with ui.column().classes("w-full gap-3"):
                    for frame in pending_frames:
                        preview = video_prompt_by_frame_id.get(frame.id, {})
                        with ui.element("div").classes(
                            "border border-[#343934] rounded-xl p-4"
                        ):
                            with ui.row().classes("w-full items-start justify-between gap-3"):
                                ui.label(f"Plano {frame.frame_number:02d}").classes(
                                    "text-sm font-semibold"
                                )
                                ui.badge(f"{frame.duration_seconds}s").classes(
                                    "blue-status-badge bg-[#243342]"
                                )
                            ui.label(str(preview.get("prompt") or frame.prompt)).classes(
                                "text-sm text-[#d8dbd8] whitespace-pre-wrap mt-2 leading-6"
                            )

            async def confirm_video_prompts(frame_ids: list[UUID] = pending_frame_ids) -> None:
                video_prompt_dialog.close()
                await _approve_video_prompts_from_ui(
                    project_id,
                    frame_ids,
                    include_canonical_references=bool(high_consistency_toggle.value),
                    loading_dialog=loading_dialog,
                    progress_callback=video_progress_callback,
                )

            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Cancelar", on_click=video_prompt_dialog.close).props("flat no-caps")
                ui.button(
                    f"Gerar {len(pending_frames)} clipe(s)",
                    icon="check_circle",
                    on_click=confirm_video_prompts,
                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
        with ui.row().classes("w-full items-center justify-end gap-3"):
            ui.button(
                f"Revisar e gerar ({len(pending_frames)})",
                icon="movie_creation",
                on_click=video_prompt_dialog.open,
            ).props("unelevated no-caps").classes("acid-bg rounded-xl")
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
                        dialog.close()
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
                        dialog.close()
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
                        ui.button(
                            "Salvar e gerar clipe",
                            icon="movie_creation",
                            on_click=generate_single_clip,
                        ).props("unelevated no-caps").classes("acid-bg rounded-xl")

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
                        ui.label(video_prompt).classes("text-sm text-[#d1d4d1] line-clamp-3")
                        with ui.row().classes("w-full justify-end mt-1"):
                            open_button = (
                                ui.button("Editar prompt", icon="edit")
                                .props("flat dense no-caps")
                                .classes("text-[#d8dbd8] rounded-xl")
                            )
                            open_button.on("click.stop", video_prompt_detail_dialog.open)

    if summary["clips"]:
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
                                ui.label(f"Clipe {i:02d}").classes(
                                    "brand-type text-2xl font-bold"
                                )
                                ui.label(f"{clip.duration_seconds}s · {clip.model}").classes(
                                    "text-sm text-[#8d938e]"
                                )
                            with ui.row().classes("gap-2 shrink-0"):
                                ui.button(
                                    "Baixar vídeo",
                                    icon="download",
                                    on_click=lambda url=clip_url, filename=download_filename: ui.download(
                                        url,
                                        filename,
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
                            dialog.close()
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
                            dialog.close()
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
                            ui.badge("Selecionado" if clip.selected else "Varia\u00e7\u00e3o").classes(
                                "bg-[#30362b] text-[#eaf878]"
                            )
                        ui.label(f"{clip.duration_seconds}s \u00b7 {clip.model}").classes(
                            "text-xs text-[#878d88]"
                        )
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
                                            on_click=lambda url=clip_url, filename=download_filename: ui.download(
                                                url,
                                                filename,
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
    elif not pending_frames:
        with ui.element("div").classes("entity-card rounded-2xl p-6 w-full mt-4"):
            ui.label("Nenhum clipe para gerar ainda").classes("brand-type text-2xl font-bold")
            ui.label(
                "Quando o storyboard estiver pronto, está tela mostrar\u00e1 os planos "
                "que podem virar clipes."
            ).classes("text-sm text-[#8d938e] leading-6")

    if summary["clips"]:
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
