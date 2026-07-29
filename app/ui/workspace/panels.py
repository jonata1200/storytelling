from typing import Any
from uuid import UUID

from nicegui import ui

from app.config.model_policy import is_mock_model
from app.config.provider_policy import (
    SUPPORTED_AI_PROVIDERS,
    effective_provider_for_channel,
    provider_api_key,
    provider_display_name,
    provider_model,
)
from app.config.settings import get_settings
from app.generation.model_settings import NARRATIVE_TASKS, TASK_LABELS
from app.generation.models import ProjectModelSetting
from app.production.models import ProjectProductionSettings
from app.production.service import (
    ASPECT_RATIOS,
    CONTENT_TYPES,
    RESOLUTIONS,
    WORKFLOW_MODES,
    resolve_image_model,
    resolve_video_model,
)
from app.storyboards.models import StoryboardFrame, Timeline, TimelineItem
from app.ui.layout.components import button_classes as _button_classes
from app.ui.layout.components import card_classes as _card_classes
from app.ui.layout.components import muted as _muted
from app.ui.project.actions import (
    _save_model_setting,
    _save_production_setup,
)


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
                "text-xs px-2 py-1 rounded-md bg-amber-950 text-amber-200 "
                "border border-amber-800"
            )
        _muted(
            "Use apenas modelos reais do provider escolhido. Modelos :free e mock ficam bloqueados "
            "para evitar travamentos e respostas falsas."
        )
        for task in NARRATIVE_TASKS:
            setting = settings_by_task.get(task)
            provider_value = (
                setting.provider
                if setting and setting.provider in SUPPORTED_AI_PROVIDERS
                else configured_text_provider
            )
            model_value = (
                setting.model
                if setting and not is_mock_model(setting.model)
                else provider_model(app_settings, provider_value, "text")
            )
            with ui.row().classes("w-full items-end gap-2"):
                ui.label(TASK_LABELS[task]).classes("w-28 text-sm text-slate-300")
                provider_select = ui.select(
                    list(SUPPORTED_AI_PROVIDERS),
                    label="Provedor",
                    value=provider_value,
                ).classes("w-36")
                model_input = ui.input("Modelo", value=model_value).classes("flex-1")
                ui.button(
                    "Salvar",
                    icon="save",
                    on_click=(
                        lambda task=task,
                        provider_select=provider_select,
                        model_input=model_input: (
                            _save_model_setting(
                                project_id,
                                task,
                                provider_select.value,
                                model_input.value,
                            )
                        )
                    ),
                ).classes("bg-slate-800 hover:bg-slate-700 rounded-md")


def _render_director_cockpit(settings: ProjectProductionSettings, counts: dict[str, int]) -> None:
    flow = [
        ("Script", counts["scripts"]),
        ("Cenas", counts["scenes"] + counts["shots"]),
        ("Assets", counts["characters"] + counts["visual_refs"]),
        ("Storyboard", counts["frames"]),
        ("Video", counts["clips"]),
        ("Timeline", counts["exports"]),
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
            "Fluxo integrado estilo estúdio: ideia, roteiro, ativos, storyboard, render, "
            "timeline e exportação sem trocar de ferramenta."
        )
        with ui.row().classes("w-full items-center gap-2"):
            for index, (label, value) in enumerate(flow):
                with ui.column().classes("items-center gap-1"):
                    ui.label(label).classes("text-sm font-semibold")
                    ui.label(str(value)).classes(
                        "w-10 h-10 rounded-full bg-cyan-950 text-cyan-100 "
                        "flex items-center justify-center font-mono border border-cyan-800"
                    )
                if index < len(flow) - 1:
                    ui.icon("arrow_forward").classes("text-slate-500")


def _render_core_setup(project_id: UUID, settings: ProjectProductionSettings) -> None:
    app_settings = get_settings()
    configured_image_provider = effective_provider_for_channel(app_settings, "image")
    configured_video_provider = effective_provider_for_channel(app_settings, "video")
    effective_image_model = resolve_image_model(
        settings.image_model,
        provider_model(app_settings, configured_image_provider, "image"),
    )
    effective_video_model = resolve_video_model(
        settings.video_model,
        provider_model(app_settings, configured_video_provider, "video"),
    )
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center gap-2"):
            ui.icon("tune").classes("text-cyan-300")
            ui.label("Core Setup").classes("text-lg font-semibold")
        _muted("Configure formato, workflow e modelos antes de gerar clipes caros.")
        with ui.grid(columns=2).classes("w-full gap-3"):
            content_type = ui.select(
                CONTENT_TYPES,
                label="Tipo de conteúdo",
                value=settings.content_type,
            )
            aspect_ratio = ui.select(
                ASPECT_RATIOS,
                label="Aspect ratio",
                value=settings.aspect_ratio,
            )
            image_resolution = ui.select(
                RESOLUTIONS,
                label="Imagem",
                value=settings.image_resolution,
            )
            video_resolution = ui.select(
                RESOLUTIONS,
                label="Video",
                value=settings.video_resolution,
            )
            workflow_mode = ui.select(
                WORKFLOW_MODES,
                label="Workflow",
                value=settings.workflow_mode,
            )
            motion_intensity = ui.number(
                "Movimento",
                value=settings.motion_intensity,
                min=1,
                max=10,
            )
            image_model = ui.input("Modelo de imagem", value=effective_image_model)
            video_model = ui.input("Modelo de vídeo", value=effective_video_model)

        async def save() -> None:
            await _save_production_setup(
                project_id,
                {
                    "content_type": content_type.value,
                    "aspect_ratio": aspect_ratio.value,
                    "image_resolution": image_resolution.value,
                    "video_resolution": video_resolution.value,
                    "workflow_mode": workflow_mode.value,
                    "motion_intensity": int(motion_intensity.value or 5),
                    "image_model": image_model.value,
                    "video_model": video_model.value,
                },
            )

        ui.button("Salvar Core Setup", icon="save", on_click=save).classes(_button_classes())


def _render_asset_canvas(summary: dict[str, Any]) -> None:
    groups = [
        ("Personagens", summary["characters"], "person"),
        ("Cenários", summary["locations"], "location_on"),
        ("Objetos", summary["props"], "category"),
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


def _render_storyboard_grid(frames: list[StoryboardFrame]) -> None:
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center gap-2"):
            ui.icon("grid_view").classes("text-cyan-300")
            ui.label("Storyboard Grid").classes("text-lg font-semibold")
        _muted("Revise a estrutura quadro a quadro antes de converter tudo em vídeo.")
        if not frames:
            ui.label("Gere storyboards para preencher a grade.").classes("text-sm text-slate-500")
            return
        with ui.grid(columns=3).classes("w-full gap-3"):
            for frame in sorted(frames, key=lambda item: item.frame_number):
                with ui.card().classes(_card_classes("min-h-32")):
                    ui.label(f"Frame {frame.frame_number:03d}").classes("text-xs text-cyan-200")
                    ui.label(frame.narration_text[:120]).classes("text-sm text-slate-300")
                    ui.label(f"{frame.duration_seconds}s").classes("text-xs text-slate-500")


def _render_timeline_strip(timeline: Timeline | None, items: list[TimelineItem]) -> None:
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center gap-2"):
            ui.icon("timeline").classes("text-cyan-300")
            ui.label("Montagem da timeline").classes("text-lg font-semibold")
        if timeline is None:
            ui.label("A montagem aparece quando os clipes estiverem prontos.").classes(
                "text-sm text-slate-500"
            )
            return
        ui.label(f"{timeline.name} · {timeline.duration_seconds}s").classes(
            "text-sm text-slate-300"
        )
        with ui.row().classes("w-full gap-1 overflow-x-auto"):
            for item in items:
                width = max(44, min(160, (item.end_ms - item.start_ms) // 80))
                is_video = item.layer == "video"
                color = "bg-cyan-900" if is_video else "bg-emerald-900"
                label = "video" if is_video else "audio"
                ui.label(label).classes(
                    f"{color} text-xs text-slate-100 rounded px-2 py-3 text-center"
                ).style(f"width: {width}px")


def _format_duration_ms(value: int | None) -> str:
    if value is None:
        return "-"
    if value >= 1000:
        return f"{value / 1000:.1f}s"
    return f"{value}ms"


def _render_execution_summary(execution_summary: Any | None) -> None:
    if execution_summary is None:
        return
    metrics = list(getattr(execution_summary, "prompt_metrics", []) or [])
    recent_jobs = list(getattr(execution_summary, "recent_jobs", []) or [])[:8]
    recent_prompts = list(getattr(execution_summary, "prompt_executions", []) or [])[:8]
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center justify-between w-full gap-3"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("query_stats").classes("text-cyan-300")
                ui.label("Execuções IA").classes("text-lg font-semibold")
            ui.badge(f"{len(recent_jobs)} job(s) recentes").classes(
                "bg-slate-800 text-slate-200"
            )
        if not metrics and not recent_jobs and not recent_prompts:
            ui.label("Sem execuções registradas para este projeto.").classes(
                "text-sm text-slate-500"
            )
            return
        if metrics:
            with ui.grid(columns=3).classes("w-full gap-3"):
                for metric in metrics[:6]:
                    with ui.column().classes(
                        "gap-1 rounded-md border border-slate-800 bg-slate-950 p-3"
                    ):
                        ui.label(str(metric.task)).classes("text-sm font-semibold")
                        ui.label(f"{metric.count} chamada(s)").classes("text-xs text-slate-400")
                        ui.label(_format_duration_ms(metric.average_duration_ms)).classes(
                            "text-xs text-cyan-200"
                        )
        if recent_jobs:
            ui.label("Jobs recentes").classes("text-sm font-semibold text-slate-200")
            with ui.column().classes("w-full gap-2"):
                for job in recent_jobs:
                    status = str(job.status).lower()
                    color = "text-emerald-300" if status == "succeeded" else "text-amber-300"
                    if status == "failed":
                        color = "text-rose-300"
                    label = job.step or job.job_type
                    with ui.row().classes(
                        "w-full items-center justify-between gap-3 rounded-md "
                        "border border-slate-800 px-3 py-2"
                    ):
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(str(label)).classes("text-sm font-semibold")
                            ui.label(f"{job.provider} · {job.model}").classes(
                                "text-xs text-slate-500"
                            )
                            if job.error:
                                ui.label(str(job.error)[:180]).classes("text-xs text-rose-300")
                        with ui.column().classes("items-end gap-0 shrink-0"):
                            ui.label(status).classes(f"text-xs font-semibold {color}")
                            ui.label(f"{job.progress}%").classes("text-xs text-slate-500")
        elif recent_prompts:
            ui.label("Prompts recentes").classes("text-sm font-semibold text-slate-200")
            with ui.column().classes("w-full gap-2"):
                for prompt in recent_prompts:
                    with ui.row().classes(
                        "w-full items-center justify-between gap-3 rounded-md "
                        "border border-slate-800 px-3 py-2"
                    ):
                        ui.label(str(prompt.task)).classes("text-sm font-semibold")
                        ui.label(
                            f"{prompt.provider} · {prompt.model} · "
                            f"{_format_duration_ms(prompt.duration_ms)}"
                        ).classes("text-xs text-slate-500")


def _format_usd(value: Any) -> str:
    try:
        return f"US$ {float(value):.4f}"
    except (TypeError, ValueError):
        return "US$ 0.0000"


def _render_cost_summary(cost_summary: Any | None) -> None:
    if cost_summary is None:
        return
    stages = list(getattr(cost_summary, "by_stage", []) or [])
    providers = list(getattr(cost_summary, "by_provider", []) or [])
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center justify-between w-full gap-3"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("paid").classes("text-cyan-300")
                ui.label("Custos por etapa").classes("text-lg font-semibold")
            ui.badge(_format_usd(getattr(cost_summary, "total_cost", 0))).classes(
                "bg-slate-800 text-slate-200"
            )
        if not stages and not providers:
            ui.label("Sem custos registrados para este projeto.").classes("text-sm text-slate-500")
            return
        if stages:
            with ui.grid(columns=3).classes("w-full gap-3"):
                for item in stages[:6]:
                    with ui.column().classes(
                        "gap-1 rounded-md border border-slate-800 bg-slate-950 p-3"
                    ):
                        ui.label(str(item.key)).classes("text-sm font-semibold")
                        ui.label(_format_usd(item.total_cost)).classes("text-xs text-cyan-200")
                        ui.label(f"real { _format_usd(item.actual_cost) }").classes(
                            "text-xs text-slate-500"
                        )
        if providers:
            ui.label("Providers").classes("text-sm font-semibold text-slate-200")
            with ui.row().classes("w-full gap-2"):
                for item in providers[:6]:
                    ui.badge(f"{item.key}: {_format_usd(item.total_cost)}").classes(
                        "bg-slate-900 text-slate-200 border border-slate-800"
                    )

