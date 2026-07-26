from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from nicegui import ui

from app.config.settings import get_settings
from app.database.session import AsyncSessionLocal
from app.storyboards.service import (
    approve_storyboard_prompt,
    approve_storyboard_prompts,
    generate_animatic_bundle,
    generate_storyboard_frames,
    storyboard_frames_need_generation,
    storyboard_prompts_need_approval,
    update_storyboard_prompt,
)
from app.ui.shared.page_config import BLOCKING_DIALOG_PROPS, friendly_ai_error, show_ai_error_popup
from app.ui.visual.actions import _approve_video_prompts_from_ui
from app.ui.visual.helpers import asset_url
from app.ui.workspace.panels import _render_timeline_strip

SectionTitle = Callable[[str, str, str | None, Any | None], None]
LoadingDialogFactory = Callable[[str, str], Any]


async def _generate_storyboards_when_prompts_are_ready(
    session: Any,
    project_id: UUID,
    script_id: UUID,
) -> int | None:
    if await storyboard_prompts_need_approval(session, project_id, script_id):
        return None
    frames = await generate_storyboard_frames(session, project_id, script_id)
    if frames is None:
        return None
    if not await storyboard_frames_need_generation(session, project_id, script_id):
        await generate_animatic_bundle(session, project_id, script_id)
    return len(frames)


async def _approve_storyboard_prompts_from_ui(
    project_id: UUID,
    script_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    if loading_dialog is not None:
        loading_dialog.open()
    try:
        async with AsyncSessionLocal() as session:
            approved_count = await approve_storyboard_prompts(session, project_id, script_id)
            generated_count = await _generate_storyboards_when_prompts_are_ready(
                session,
                project_id,
                script_id,
            )
        if generated_count is not None:
            ui.notify(
                (
                    f"{approved_count} prompt(s) aprovado(s). "
                    f"{generated_count} storyboard(s) gerado(s)."
                ),
                color="positive",
            )
            ui.navigate.reload()
            return
        ui.notify(
            (
                f"{approved_count} prompt(s) de storyboard aprovado(s)."
                if approved_count
                else "Os prompts de storyboard já estavam aprovados."
            ),
            color="positive",
        )
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        if loading_dialog is not None:
            loading_dialog.close()


async def _approve_storyboard_prompt_from_ui(
    project_id: UUID,
    script_id: UUID,
    shot_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    if loading_dialog is not None:
        loading_dialog.open()
    try:
        async with AsyncSessionLocal() as session:
            approved = await approve_storyboard_prompt(session, project_id, script_id, shot_id)
            generated_count = (
                await _generate_storyboards_when_prompts_are_ready(session, project_id, script_id)
                if approved
                else None
            )
        if generated_count is not None:
            ui.notify(
                f"Ultimo prompt aprovado. {generated_count} storyboard(s) gerado(s).",
                color="positive",
            )
            ui.navigate.reload()
            return
        ui.notify(
            (
                "Prompt de storyboard aprovado."
                if approved
                else "Este prompt de storyboard ja estava aprovado."
            ),
            color="positive",
        )
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        if loading_dialog is not None:
            loading_dialog.close()


async def _save_storyboard_prompt_from_ui(
    project_id: UUID,
    script_id: UUID,
    shot_id: UUID,
    prompt: str,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            updated = await update_storyboard_prompt(
                session,
                project_id,
                script_id,
                shot_id,
                prompt,
            )
        ui.notify(
            (
                "Prompt de storyboard atualizado."
                if updated
                else "Nao encontrei o prompt de storyboard selecionado."
            ),
            color="positive" if updated else "warning",
        )
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


async def _generate_storyboards_from_ui(
    project_id: UUID,
    script_id: UUID,
    *,
    shot_id: UUID | None = None,
    approved_only: bool = False,
    force: bool = False,
    loading_dialog: Any | None = None,
) -> None:
    if loading_dialog is not None:
        loading_dialog.open()
    try:
        async with AsyncSessionLocal() as session:
            frames = await generate_storyboard_frames(
                session,
                project_id,
                script_id,
                shot_id=shot_id,
                force=force,
                approved_only=approved_only,
            )
            if not frames:
                ui.notify("Não foi possível gerar storyboards.", color="negative")
                return
            if not await storyboard_frames_need_generation(session, project_id, script_id):
                await generate_animatic_bundle(session, project_id, script_id)
        ui.notify("Storyboards gerados.", color="positive")
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
    generation_dialog = (
        loading_dialog_factory(
            "Gerando storyboards",
            "A IA está criando os quadros aprovados do storyboard.",
        )
        if loading_dialog_factory is not None
        else None
    )
    prompt_dialog: Any | None = None
    if script_id is not None and prompt_previews:
        with (
            ui.dialog().props(BLOCKING_DIALOG_PROPS) as prompt_dialog,
            ui.card().classes("entity-card rounded-2xl p-6 w-[min(920px,94vw)] max-h-[86vh]"),
        ):
            ui.label("Aprovar prompts de storyboard").classes("brand-type text-2xl font-bold")
            ui.label(
                "Revise os prompts por cena e plano antes de liberar a geração das imagens."
            ).classes("text-sm text-[#8d938e]")
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

            async def confirm_storyboard_prompts() -> None:
                prompt_dialog.close()
                await _approve_storyboard_prompts_from_ui(
                    project_id,
                    script_id,
                    loading_dialog=generation_dialog,
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
    if script_id is not None and prompt_previews and not pending_prompt_previews:
        with ui.row().classes("w-full items-center justify-end gap-2 mb-2"):
            if not pending_prompt_previews and missing_frame_previews:
                ui.button(
                    f"Gerar storyboards aprovados ({len(missing_frame_previews)})",
                    icon="auto_awesome",
                    on_click=lambda: _generate_storyboards_from_ui(
                        project_id,
                        script_id,
                        loading_dialog=generation_dialog,
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
                                script_id,
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
                with ui.column().classes("p-4 gap-1"):
                    ui.label(f"PLANO {frame.frame_number:02d} · {frame.duration_seconds}s").classes(
                        "text-xs acid font-semibold"
                    )
                    ui.label(frame.prompt).classes("text-sm text-[#d1d4d1] line-clamp-3")
        if not summary["frames"]:
            ui.label(
                "O Diretor IA pode criar os quadros quando roteiro e ativos estiverem prontos."
            ).classes("text-[#858b86]")


def render_video_area(
    project_id: UUID,
    summary: dict[str, Any],
    *,
    section_title: SectionTitle,
) -> None:
    section_title(
        "Produção de vídeo",
        "Gere clipes, escolha variações e finalize sua montagem.",
        None,
        None,
    )
    sorted_frames = sorted(summary["frames"], key=lambda frame: frame.frame_number)
    clip_frame_ids = {clip.storyboard_frame_id for clip in summary["clips"]}
    pending_frames = [frame for frame in sorted_frames if frame.id not in clip_frame_ids]
    if pending_frames:
        pending_frame_ids = [frame.id for frame in pending_frames]
        with (
            ui.dialog().props(BLOCKING_DIALOG_PROPS) as video_prompt_dialog,
            ui.card().classes("entity-card rounded-2xl p-6 w-[min(820px,92vw)] max-h-[82vh]"),
        ):
            ui.label("Aprovar prompts de vídeo").classes("brand-type text-2xl font-bold")
            ui.label("Confira os prompts antes de gerar os clipes a partir do storyboard.").classes(
                "text-sm text-[#8d938e]"
            )
            with ui.scroll_area().classes("w-full max-h-[52vh] pr-2"):
                with ui.column().classes("w-full gap-3"):
                    for frame in pending_frames:
                        with ui.element("div").classes("border border-[#343934] rounded-xl p-4"):
                            ui.label(
                                f"PLANO {frame.frame_number:02d} - {frame.duration_seconds}s"
                            ).classes("text-xs acid font-semibold")
                            ui.label(frame.prompt).classes(
                                "text-sm text-[#d8dbd8] whitespace-pre-wrap"
                            )

            async def confirm_video_prompts(
                frame_ids: list[UUID] = pending_frame_ids,
            ) -> None:
                video_prompt_dialog.close()
                await _approve_video_prompts_from_ui(project_id, frame_ids)

            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Cancelar", on_click=video_prompt_dialog.close).props("flat no-caps")
                ui.button(
                    "Aprovar e gerar clipes",
                    icon="check_circle",
                    on_click=confirm_video_prompts,
                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
        with ui.row().classes("w-full justify-end mb-3"):
            ui.button(
                f"Aprovar prompts pendentes ({len(pending_frames)})",
                icon="check_circle",
                on_click=video_prompt_dialog.open,
            ).props("unelevated no-caps").classes("acid-bg rounded-xl")
    with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
        for i, clip in enumerate(summary["clips"], 1):
            with ui.element("div").classes("entity-card rounded-2xl overflow-hidden"):
                with ui.element("div").classes(
                    "visual-placeholder aspect-video flex items-center justify-center relative"
                ):
                    ui.button(icon="play_arrow").props("round unelevated").classes("acid-bg")
                with ui.column().classes("p-4 gap-2"):
                    with ui.row().classes("w-full justify-between"):
                        ui.label(f"Clipe {i:02d}").classes("font-semibold")
                        ui.badge("Selecionado" if clip.selected else "Variação").classes(
                            "bg-[#30362b] text-[#eaf878]"
                        )
                    ui.label(f"{clip.duration_seconds}s · {clip.model}").classes(
                        "text-xs text-[#878d88]"
                    )
        if not summary["clips"] and not pending_frames:
            ui.label(
                "O Diretor IA pode criar os clipes quando o storyboard estiver pronto."
            ).classes("text-[#858b86]")
        elif not summary["clips"]:
            ui.label("Aprove os prompts pendentes acima para criar os primeiros clipes.").classes(
                "text-[#858b86]"
            )
    ui.label("Timeline").classes("brand-type text-2xl font-bold mt-6")
    _render_timeline_strip(summary["timeline"], summary["timeline_items"])
