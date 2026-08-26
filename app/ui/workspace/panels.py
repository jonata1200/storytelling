from typing import Any
from uuid import UUID

from nicegui import ui

from app.config.provider_policy import (
    effective_provider_for_channel,
    provider_api_key,
    provider_display_name,
)
from app.config.settings import OLLAMA_CLOUD_TEXT_MODELS, get_settings
from app.generation.model_settings import NARRATIVE_TASKS, TASK_LABELS
from app.generation.models import ProjectModelSetting
from app.production.models import ProjectProductionSettings
from app.production.service import (
    ASPECT_RATIOS,
    CONTENT_TYPES,
    normalize_image_aspect_ratio,
)
from app.ui.layout.components import button_classes as _button_classes
from app.ui.layout.components import card_classes as _card_classes
from app.ui.layout.components import muted as _muted
from app.ui.project.actions import (
    _save_model_setting,
    _save_production_setup,
)
from app.ui.workspace.rules import CONTINUOUS_VIDEO_WORKFLOW_MODE


def _render_model_settings(project_id: UUID, settings_list: list[ProjectModelSetting]) -> None:
    settings_by_task = {item.task: item for item in settings_list}
    app_settings = get_settings()
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center gap-2"):
            ui.icon("hub").classes("text-cyan-300")
            ui.label("Modelos de IA por etapa").classes("text-lg font-semibold")
        configured_text_provider = effective_provider_for_channel(app_settings, "text")
        if provider_api_key(app_settings, configured_text_provider):
            ui.label(f"{provider_display_name(configured_text_provider)} configurado").classes(
                "text-xs px-2 py-1 rounded-md bg-emerald-950 text-emerald-200 "
                "border border-emerald-800"
            )
        else:
            ui.label(
                f"{configured_text_provider.upper()}_API_KEY ausente ou inválida: "
                "modelos reais não serão chamados"
            ).classes(
                "text-xs px-2 py-1 rounded-md bg-amber-950 text-amber-200 border border-amber-800"
            )
        _muted("Escolha o modelo Ollama Cloud usado em cada etapa narrativa.")
        for task in NARRATIVE_TASKS:
            task_setting = settings_by_task.get(task)
            selected_model = (
                task_setting.model
                if task_setting is not None
                else app_settings.ollama_cloud_default_model
            )
            with ui.row().classes("w-full items-end gap-2"):
                ui.label(TASK_LABELS[task]).classes("w-28 text-sm text-slate-300")
                ui.label("Ollama Cloud").classes("w-36 text-sm text-slate-300")
                ui.select(
                    list(OLLAMA_CLOUD_TEXT_MODELS),
                    value=selected_model,
                    on_change=lambda event, selected_task=task: _save_model_setting(
                        project_id,
                        selected_task,
                        "ollama_cloud",
                        str(event.value),
                    ),
                ).props("outlined dense options-dense").classes("flex-1")


def _render_director_cockpit(settings: ProjectProductionSettings, counts: dict[str, int]) -> None:
    steps = [
        ("Script", counts["scripts"]),
        ("Cenas", counts["scenes"] + counts["shots"]),
        ("Assets", counts["characters"] + counts["visual_refs"]),
        ("Video", counts["clips"]),
    ]
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center justify-between w-full"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("smart_toy").classes("text-cyan-300 text-2xl")
                ui.label("AI Director Cockpit").classes("text-xl font-semibold")
            ui.label(f"Episodio {settings.episode_number}").classes(
                "text-xs px-2 py-1 rounded-md bg-slate-800 text-slate-300"
            )
        _muted(
            "Fluxo integrado estilo estúdio: ideia, roteiro, ativos e vídeo "
            "sem trocar de ferramenta."
        )
        with ui.row().classes("w-full items-center gap-2"):
            for index, (label, value) in enumerate(steps):
                with ui.column().classes("items-center gap-1"):
                    ui.label(label).classes("text-sm font-semibold")
                    ui.label(str(value)).classes(
                        "w-10 h-10 rounded-full bg-cyan-950 text-cyan-100 "
                        "flex items-center justify-center font-mono border border-cyan-800"
                    )
                if index < len(steps) - 1:
                    ui.icon("arrow_forward").classes("text-slate-500")


def _render_core_setup(project_id: UUID, settings: ProjectProductionSettings) -> None:
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center gap-2"):
            ui.icon("tune").classes("text-cyan-300")
            ui.label("Core Setup").classes("text-lg font-semibold")
        _muted("Configure formato, resolução e movimento dos vídeos.")
        with ui.grid(columns=2).classes("w-full gap-3"):
            content_type = ui.select(
                CONTENT_TYPES,
                label="Tipo de conteúdo",
                value=settings.content_type,
            )
            aspect_ratio = ui.select(
                ASPECT_RATIOS,
                label="Aspect ratio",
                value=normalize_image_aspect_ratio(settings.aspect_ratio),
            )
            motion_intensity = ui.number(
                "Movimento",
                value=settings.motion_intensity,
                min=1,
                max=10,
            )
            ui.label(
                "O v\u00eddeo \u00e9 criado manualmente manualmente; "
                "apenas imagens s\u00e3o geradas por IA aqui."
            ).classes("text-xs text-slate-500 self-end")

        async def save() -> None:
            await _save_production_setup(
                project_id,
                {
                    "content_type": content_type.value,
                    "aspect_ratio": aspect_ratio.value,
                    "workflow_mode": CONTINUOUS_VIDEO_WORKFLOW_MODE,
                    "motion_intensity": int(motion_intensity.value or 5),
                },
            )

        ui.button("Salvar Core Setup", icon="save", on_click=save).classes(_button_classes())


def _render_asset_canvas(summary: dict[str, Any]) -> None:
    groups = [
        ("Personagens", summary["characters"], "person"),
        ("Cenários", summary["locations"], "location_on"),
        ("Referências", summary["visual_refs"], "image"),
    ]
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center gap-2"):
            ui.icon("dashboard_customize").classes("text-cyan-300")
            ui.label("Asset Canvas").classes("text-lg font-semibold")
        _muted("Ativos reutilizaveis ficam centralizados para preservar consistencia visual.")
        with ui.grid(columns=4).classes("w-full gap-3"):
            for title, items, icon_name in groups:
                with ui.column().classes("gap-2"):
                    ui.label(title).classes("font-semibold")
                    if not items:
                        ui.label("vazio").classes("text-sm text-slate-500")
                    for item in items:
                        name = getattr(item, "name", getattr(item, "view_type", "item"))
                        with ui.card().classes(_card_classes("w-full p-3")):
                            ui.icon(icon_name).classes("text-cyan-300")
                            ui.label(str(name)).classes("text-sm font-semibold")
