from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from nicegui import ui

from app.config.settings import get_settings
from app.ui.shared.page_config import BLOCKING_DIALOG_PROPS
from app.ui.visual.actions import _approve_video_prompts_from_ui
from app.ui.visual.helpers import asset_url
from app.ui.workspace.panels import _render_timeline_strip

SectionTitle = Callable[[str, str, str | None, Any | None], None]


def _local_asset_file_exists(storage_uri: str) -> bool:
    if not storage_uri:
        return False
    if storage_uri.startswith(("http://", "https://", "data:")):
        return True
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
    return asset_url(asset.storage_uri)


def render_storyboard_area(
    project_id: UUID,
    summary: dict[str, Any],
    *,
    section_title: SectionTitle,
) -> None:
    section_title(
        "Storyboard",
        "Planeje enquadramentos e ritmo antes de gerar os clipes.",
        None,
        None,
    )
    with ui.row().classes("w-full gap-3 mb-3"):
        for label, value in [
            ("Quadros", summary["counts"]["frames"]),
            ("Planos", summary["counts"]["shots"]),
            ("Duração", f"{sum(f.duration_seconds for f in summary['frames'])}s"),
        ]:
            with ui.element("div").classes("glass rounded-xl px-4 py-2"):
                ui.label(label).classes("text-[10px] uppercase text-[#777d78]")
                ui.label(str(value)).classes("text-lg font-bold")
    with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
        for frame in sorted(summary["frames"], key=lambda f: f.frame_number):
            image_url = _storyboard_frame_image_url(summary, frame)
            with ui.element("div").classes("entity-card rounded-2xl overflow-hidden"):
                with ui.element("div").classes(
                    "visual-placeholder aspect-video p-0 flex items-center justify-center bg-black"
                ):
                    if image_url:
                        ui.image(image_url).classes(
                            "w-full h-full object-contain bg-black"
                        ).props("fit=contain")
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
        with ui.dialog().props(BLOCKING_DIALOG_PROPS) as video_prompt_dialog, ui.card().classes(
            "entity-card rounded-2xl p-6 w-[min(820px,92vw)] max-h-[82vh]"
        ):
            ui.label("Aprovar prompts de vídeo").classes("brand-type text-2xl font-bold")
            ui.label(
                "Confira os prompts antes de gerar os clipes a partir do storyboard."
            ).classes("text-sm text-[#8d938e]")
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
            ui.label(
                "Aprove os prompts pendentes acima para criar os primeiros clipes."
            ).classes("text-[#858b86]")
    ui.label("Timeline").classes("brand-type text-2xl font-bold mt-6")
    _render_timeline_strip(summary["timeline"], summary["timeline_items"])




