# ruff: noqa: E501

import asyncio
import logging
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

from nicegui import app as nicegui_app  # noqa: F401
from nicegui import ui
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.provider_policy import (
    ProviderChannel,
    effective_provider_for_channel,
    provider_model,
)
from app.config.settings import get_settings
from app.database.session import AsyncSessionLocal
from app.generation.model_settings import (
    ensure_default_model_settings,
)
from app.production.service import (
    update_production_settings,
)
from app.projects.models import Project
from app.projects.schemas import ProjectCreate
from app.projects.service import (
    create_project,
    sync_project_title,
)
from app.storytelling.models import (
    Briefing,
    Script,
    StoryIdea,
)
from app.storytelling.reference_upload import persist_reference_uploads
from app.storytelling.schemas import BriefingCreate
from app.storytelling.service import (
    coerce_duration_minutes,
    create_briefing,
    create_story_idea_from_payload,
    generate_script,
    generate_story_ideas,
)
from app.ui.layout.components import (
    button_classes as _button_classes,
)
from app.ui.layout.components import (
    card_classes as _card_classes,
)
from app.ui.layout.navigation import (
    home_sidebar as _home_sidebar,  # noqa: F401
)
from app.ui.layout.navigation import (
    save_avatar_file as _save_avatar_file,  # noqa: F401
)
from app.ui.layout.navigation import (
    studio_logo as _studio_logo,  # noqa: F401
)
from app.ui.layout.navigation import (
    theme_toggle as _theme_toggle,  # noqa: F401
)
from app.ui.layout.navigation import (
    user_avatar as _user_avatar,  # noqa: F401
)
from app.ui.layout.navigation import (
    workspace_header as _workspace_header,  # noqa: F401
)
from app.ui.layout.theme import (
    apply_body_style as _body_style,  # noqa: F401
)
from app.ui.page_runtime import (
    _ai_action_is_stale as _ai_action_is_stale,  # noqa: F401
)
from app.ui.page_runtime import (
    _asset_url as _asset_url,  # noqa: F401
)
from app.ui.page_runtime import (
    _assistant_panel as _assistant_panel,  # noqa: F401
)
from app.ui.page_runtime import (
    _notify_ai_action_failure_once as _notify_ai_action_failure_once,  # noqa: F401
)
from app.ui.page_runtime import (
    _ordered_scenes as _ordered_scenes,  # noqa: F401
)
from app.ui.page_runtime import (
    _project_ai_action as _project_ai_action,  # noqa: F401
)
from app.ui.page_runtime import (
    _render_assets_area as _render_assets_area,  # noqa: F401
)
from app.ui.page_runtime import (
    _render_dubbing_area as _render_dubbing_area,  # noqa: F401
)
from app.ui.page_runtime import (
    _render_finalization_area as _render_finalization_area,  # noqa: F401
)
from app.ui.page_runtime import (
    _render_script_area as _render_script_area,  # noqa: F401
)
from app.ui.page_runtime import (
    _render_storyboard_area as _render_storyboard_area,  # noqa: F401
)
from app.ui.page_runtime import (
    _render_video_area as _render_video_area,  # noqa: F401
)
from app.ui.page_runtime import (
    _save_script_from_ui as _save_script_from_ui,  # noqa: F401
)
from app.ui.page_runtime import (
    _section_title as _section_title,  # noqa: F401
)
from app.ui.page_runtime import (
    _sync_ai_action_events_to_chat as _sync_ai_action_events_to_chat,  # noqa: F401
)
from app.ui.page_runtime import (
    register_ui_pages as register_ui_pages,  # noqa: F401
)
from app.ui.project.actions import (
    _create_next_episode as _project_action_create_next_episode,
)
from app.ui.project.actions import (
    _delete_lab_idea_from_ui as _project_action_delete_lab_idea_from_ui,
)
from app.ui.project.actions import (
    _delete_project_from_ui as _project_action_delete_project_from_ui,
)
from app.ui.project.actions import (
    _purge_all_ideas_from_ui as _project_action_purge_all_ideas_from_ui,
)
from app.ui.project.actions import (
    _purge_all_projects_from_ui as _project_action_purge_all_projects_from_ui,
)
from app.ui.project.actions import (
    _purge_application_data_from_ui as _project_action_purge_application_data_from_ui,
)
from app.ui.project.actions import (
    _rename_project_from_ui as _project_action_rename_project_from_ui,
)
from app.ui.project.actions import (
    _save_model_setting as _project_action_save_model_setting,
)
from app.ui.project.actions import (
    _save_production_setup as _project_action_save_production_setup,
)
from app.ui.project.cards import render_project_card
from app.ui.project.data import (
    latest as _latest,
)
from app.ui.project.data import (
    project_cards as _project_cards,  # noqa: F401
)
from app.ui.project.data import (
    project_summary as _project_summary,  # noqa: F401
)
from app.ui.project.production_steps import _run_step
from app.ui.project.text import (
    compact_project_title as _compact_project_title,
)
from app.ui.project.text import (
    format_idea_payload_for_project as _format_idea_payload_for_project,
)
from app.ui.project.workflows import (
    _generate_initial_script_in_background,
    _reload_project_when_script_ready,
    _set_project_ai_action_status,
)
from app.ui.project.workflows import (
    _log_ai_background_failure as _workflow_log_ai_background_failure,
)
from app.ui.shared import assistant_state
from app.ui.shared.assistant_state import (  # noqa: F401
    safe_client_navigation as _safe_client_navigation,
)
from app.ui.shared.assistant_state import (  # noqa: F401
    safe_refresh as _safe_refresh,
)
from app.ui.shared.page_config import (
    BLOCKING_DIALOG_PROPS,
    DEFAULT_STORY_DURATION_MINUTES,
    LoadingStatus,
    ProductionStep,
    safe_close_ui_element,
    script_progress_poll_interval,
    step_loading_copy,
)
from app.ui.shared.page_config import IDEA_COUNT_OPTIONS as IDEA_COUNT_OPTIONS  # noqa: F401
from app.ui.shared.page_config import IDEA_GENRES as IDEA_GENRES  # noqa: F401
from app.ui.shared.page_config import (
    PRODUCTION_STEPS as PAGE_PRODUCTION_STEPS,
)
from app.ui.shared.page_config import STORY_DURATION_OPTIONS as STORY_DURATION_OPTIONS  # noqa: F401
from app.ui.shared.page_config import (
    WORKSPACE_TABS as PAGE_WORKSPACE_TABS,
)
from app.ui.shared.page_config import (
    clean_idea_title as _clean_idea_title,
)
from app.ui.shared.page_config import (
    friendly_ai_error as _page_friendly_ai_error,
)
from app.ui.shared.page_config import (
    settings_tab_key as _settings_tab_key,  # noqa: F401
)
from app.ui.shared.page_config import (
    show_ai_error_popup as _show_ai_error_popup,  # noqa: F401
)
from app.ui.visual.actions import (  # noqa: F401
    _approve_all_visual_targets_from_ui as _approve_all_visual_targets_from_ui,
)
from app.ui.visual.actions import (  # noqa: F401
    _approve_visual_target_from_ui as _approve_visual_target_from_ui,
)
from app.ui.visual.actions import (
    _current_visual_batch_requests as _current_visual_batch_requests,
)
from app.ui.visual.actions import (
    _notify_visual_action as _notify_visual_action,
)
from app.ui.visual.actions import (  # noqa: F401
    _regenerate_visual_reference_from_ui as _regenerate_visual_reference_from_ui,
)
from app.ui.visual.actions import (  # noqa: F401
    _update_visual_prompt_from_ui as _update_visual_prompt_from_ui,
)
from app.ui.visual.actions import (  # noqa: F401
    _visual_batch_requests as _visual_batch_requests,
)
from app.ui.visual.actions import (
    _visual_fallback_notice as _visual_fallback_notice,
)
from app.ui.visual.actions import (
    _visual_library_cards_ready as _visual_library_cards_ready,
)
from app.ui.visual.actions import (
    _visual_prompts_need_generation as _visual_prompts_need_generation,
)
from app.ui.visual.actions import (
    _visual_reference_used_fallback as _visual_reference_used_fallback,
)
from app.ui.visual.helpers import (  # noqa: F401
    visual_card_detail as _visual_card_detail,
)
from app.ui.visual.helpers import (  # noqa: F401
    visual_reference_asset as _visual_reference_asset,
)
from app.ui.visual.helpers import (  # noqa: F401
    visual_reference_views_for as _visual_reference_views_for,
)
from app.ui.visual.helpers import (  # noqa: F401
    visual_references_for as _visual_references_for,
)
from app.ui.workspace.assets_area import _entity_card as _entity_card
from app.ui.workspace.rules import (
    first_available_workspace_section as _first_available_workspace_section,  # noqa: F401
)
from app.ui.workspace.rules import (
    step_ready as _step_ready,
)
from app.ui.workspace.rules import (
    workspace_section_access as _workspace_section_access,  # noqa: F401
)

logger = logging.getLogger(__name__)


def _default_media_model(channel: ProviderChannel) -> str:
    settings = get_settings()
    provider = effective_provider_for_channel(settings, channel)
    return provider_model(settings, provider, channel)


PRODUCTION_STEPS = PAGE_PRODUCTION_STEPS
WORKSPACE_TABS = PAGE_WORKSPACE_TABS
_is_legacy_assistant_greeting = assistant_state.is_legacy_assistant_greeting


def _friendly_ai_error(exc: Exception) -> str:
    return _page_friendly_ai_error(exc)


def _render_project_card(project: Project, redirect_to: str) -> None:
    render_project_card(
        project,
        redirect_to,
        _rename_project_from_ui,
        _delete_project_from_ui,
    )


def _log_ai_background_failure(message: str, identifier: UUID, exc: Exception) -> None:
    _workflow_log_ai_background_failure(message, identifier, exc)


async def _sync_project_title_from_story(
    session: AsyncSession,
    project_id: UUID,
    title: object,
    *,
    source: str,
) -> None:
    clean_title = str(title or "").strip()
    if not clean_title:
        return
    await sync_project_title(
        session,
        project_id,
        clean_title,
        change_note=f"Project title synchronized from {source}",
    )


async def _generate_initial_script(
    session: AsyncSession,
    project_id: UUID,
    source_idea: dict[str, Any] | None = None,
    progress: Callable[[str], Awaitable[None]] | None = None,
) -> Script:
    if source_idea is not None:
        if progress is not None:
            await progress("Vou registrar a ideia escolhida dentro deste projeto.")
        idea = await create_story_idea_from_payload(session, project_id, source_idea)
        if idea is None:
            raise ValueError("não foi possível registrar a ideia selecionada")
    else:
        if progress is not None:
            await progress("Vou criar uma ideia base para orientar o roteiro.")
        generated_ideas = await generate_story_ideas(session, project_id)
        if not generated_ideas:
            raise ValueError("não foi possível gerar ideias iniciais")
        idea = generated_ideas[0]
    await _sync_project_title_from_story(
        session,
        project_id,
        getattr(idea, "title", ""),
        source="story idea",
    )

    if progress is not None:
        await progress("Vou escrever o roteiro cinematográfico a partir da ideia escolhida.")
    script = await generate_script(session, project_id, idea.id)
    if script is None:
        raise ValueError("não foi possível gerar roteiro")
    await _sync_project_title_from_story(
        session,
        project_id,
        getattr(script, "title", ""),
        source="script title",
    )
    return script


async def _close_loading_dialog_when_script_ready(
    project_id: UUID,
    loading_dialog: Any,
    attempt: int = 0,
) -> None:
    ready = await _reload_project_when_script_ready(project_id)
    if ready and hasattr(loading_dialog, "close"):
        safe_close_ui_element(loading_dialog)
        return
    ui.timer(
        script_progress_poll_interval(attempt + 1),
        lambda: _close_loading_dialog_when_script_ready(
            project_id,
            loading_dialog,
            attempt + 1,
        ),
        once=True,
    )


async def _retry_initial_script_from_ui(project_id: UUID, loading_dialog: Any) -> None:
    loading_dialog.open()
    async with AsyncSessionLocal() as session:
        await _set_project_ai_action_status(
            session,
            project_id,
            status="queued",
            message="A IA vai retomar a criação do roteiro inicial.",
            action="create_initial_script",
        )
    asyncio.create_task(_generate_initial_script_in_background(project_id))
    ui.timer(
        5.0,
        lambda: _close_loading_dialog_when_script_ready(project_id, loading_dialog),
        once=True,
    )
    ui.notify("Retomando a criação do roteiro.", color="positive")


async def _develop_script_for_existing_project(
    session: AsyncSession, project_id: UUID
) -> tuple[str, bool]:
    briefing = await _latest(session, Briefing, project_id)
    if briefing is None:
        return (
            "Este projeto ainda não tem briefing. Crie o projeto pelo chat inicial ou preencha o briefing primeiro.",
            False,
        )

    script = await _latest(session, Script, project_id)
    if script is not None:
        return (
            "Este projeto já tem roteiro. Posso ajudar a revisar ou seguir para a próxima etapa.",
            False,
        )

    idea = await _latest(session, StoryIdea, project_id)
    if idea is None:
        ideas = await generate_story_ideas(session, project_id)
        if not ideas:
            return "Não consegui gerar uma ideia base para este projeto.", False
        idea = ideas[0]

    script = await generate_script(session, project_id, idea.id)
    if script is None:
        return "Não consegui gerar o roteiro para este projeto.", False
    return "Roteiro criado.", True


async def _create_project_from_form(
    form: dict[str, Any],
    *,
    generate_initial_script: bool = False,
    source_idea: dict[str, Any] | None = None,
) -> None:
    try:
        duration = coerce_duration_minutes(form["duration"])
        project_id: UUID
        background_source_idea: dict[str, Any] | None = None
        async with AsyncSessionLocal() as session:
            project = await create_project(
                session,
                ProjectCreate(title=form["title"], description=form["description"]),
            )
            project_id = project.id
            await ensure_default_model_settings(session, project.id)
            await update_production_settings(
                session,
                project.id,
                {
                    "content_type": form["content_type"],
                    "aspect_ratio": form["aspect_ratio"],
                    "image_resolution": form["image_resolution"],
                    "video_resolution": form["video_resolution"],
                    "workflow_mode": form["workflow_mode"],
                    "image_model": form["image_model"],
                    "video_model": form["video_model"],
                    "motion_intensity": int(form["motion_intensity"]),
                    "metadata_json": {
                        "one_line_idea": form["one_line_idea"],
                        "source_idea": form.get("source_idea_payload"),
                    },
                },
            )
            briefing = BriefingCreate(
                theme=form["theme"],
                audience=form["audience"],
                genre=form["genre"],
                primary_emotion=form["emotion"],
                emotional_intensity=int(form["intensity"]),
                ending_type=form["ending"],
                desired_duration_minutes=Decimal(str(duration)),
                visual_style=form["visual_style"],
                content_objective=form["objective"],
                call_to_action=form["cta"] or None,
                constraints=[
                    item.strip() for item in form["constraints"].splitlines() if item.strip()
                ],
            )
            created_briefing = await create_briefing(session, project.id, briefing)
            reference_uploads = form.get("reference_uploads")
            if created_briefing is not None and isinstance(reference_uploads, list):
                await persist_reference_uploads(
                    session,
                    project.id,
                    created_briefing.artifact_id,
                    reference_uploads,
                )
            if generate_initial_script:
                await _set_project_ai_action_status(
                    session,
                    project.id,
                    status="queued",
                    message="A IA vai iniciar a criação do roteiro inicial.",
                    action="create_initial_script",
                )
                background_source_idea = dict(source_idea) if source_idea is not None else None
        if generate_initial_script:
            asyncio.create_task(
                _generate_initial_script_in_background(project_id, background_source_idea)
            )
            message = f"Projeto criado. A IA iniciou o roteiro de {duration:g} minutos."
        else:
            message = "Projeto criado com briefing inicial."
        ui.notify(message, color="positive")
        if generate_initial_script:
            destination = f"/projects/{project_id}/script"
        else:
            destination = f"/projects/{project_id}"
        ui.navigate.to(destination)
    except Exception as exc:
        ui.notify(f"Não foi possível criar o projeto: {exc}", color="negative")


async def _create_project_from_chat_prompt(
    prompt: str,
    reference_uploads: list[dict[str, Any]] | None = None,
) -> None:
    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        ui.notify("Descreva a ideia ou cole um roteiro antes de criar o projeto.", color="warning")
        return
    form = {
        "title": _compact_project_title(cleaned_prompt),
        "description": cleaned_prompt[:240],
        "theme": cleaned_prompt[:220],
        "audience": "público geral",
        "genre": "drama emocional",
        "emotion": "curiosidade",
        "intensity": 8,
        "ending": "final com revelacao afetiva",
        "duration": DEFAULT_STORY_DURATION_MINUTES,
        "visual_style": "cinemático realista vertical",
        "objective": (
            f"reter audiência com uma história completa de "
            f"{DEFAULT_STORY_DURATION_MINUTES:g} minutos"
        ),
        "cta": "",
        "constraints": "evitar violencia grafica\nmanter tom familiar",
        "one_line_idea": cleaned_prompt,
        "content_type": "short_drama",
        "aspect_ratio": "9:16",
        "workflow_mode": "keyframes_i2v",
        "image_resolution": "720x1280",
        "video_resolution": "720p",
        "motion_intensity": 5,
        "image_model": _default_media_model("image"),
        "video_model": _default_media_model("video"),
        "reference_uploads": reference_uploads or [],
    }
    await _create_project_from_form(form, generate_initial_script=True)


async def _create_project_from_idea(idea: dict[str, Any]) -> None:
    title = _clean_idea_title(idea.get("title"), "Ideia de storytelling")
    theme = str(idea.get("theme") or idea.get("premise") or title).strip()
    premise = str(idea.get("premise") or idea.get("hook") or theme).strip()
    genre = str(idea.get("genre") or "drama emocional").strip()
    emotion = str(idea.get("primary_emotion") or idea.get("final_emotion") or "curiosidade").strip()
    duration = DEFAULT_STORY_DURATION_MINUTES
    form = {
        "title": title[:80] or "Novo projeto de storytelling",
        "description": premise[:240],
        "theme": theme[:220],
        "audience": "público geral",
        "genre": genre,
        "emotion": emotion,
        "intensity": 8,
        "ending": "final com payoff emocional",
        "duration": duration,
        "visual_style": "cinemático realista vertical",
        "objective": f"desenvolver uma história completa de {duration:g} minutos",
        "cta": "",
        "constraints": (
            f"manter ritmo forte\ncriar ganchos claros\nadequar para {duration:g} minutos"
        ),
        "one_line_idea": _format_idea_payload_for_project(idea),
        "source_idea_payload": dict(idea),
        "content_type": "short_drama",
        "aspect_ratio": "9:16",
        "workflow_mode": "keyframes_i2v",
        "image_resolution": "720x1280",
        "video_resolution": "720p",
        "motion_intensity": 5,
        "image_model": _default_media_model("image"),
        "video_model": _default_media_model("video"),
    }
    await _create_project_from_form(
        form,
        generate_initial_script=True,
        source_idea=idea,
    )


async def _rename_project_from_ui(project_id: UUID, title: str, redirect_to: str) -> None:
    await _project_action_rename_project_from_ui(project_id, title, redirect_to)


async def _delete_project_from_ui(project_id: UUID, redirect_to: str) -> None:
    await _project_action_delete_project_from_ui(project_id, redirect_to)


async def _purge_application_data_from_ui() -> None:
    await _project_action_purge_application_data_from_ui()


async def _purge_all_ideas_from_ui() -> None:
    await _project_action_purge_all_ideas_from_ui()


async def _purge_all_projects_from_ui() -> None:
    await _project_action_purge_all_projects_from_ui()


async def _delete_lab_idea_from_ui(idea_id: str, source: str) -> bool:
    return await _project_action_delete_lab_idea_from_ui(idea_id, source)


async def _save_model_setting(
    project_id: UUID, task: str, provider: str | None, model: str | None
) -> None:
    await _project_action_save_model_setting(project_id, task, provider, model)


async def _save_production_setup(project_id: UUID, payload: dict[str, Any]) -> None:
    await _project_action_save_production_setup(project_id, payload)


async def _create_next_episode(project_id: UUID) -> None:
    await _project_action_create_next_episode(project_id)


def _render_loading_status(status: LoadingStatus) -> None:
    if status.now:
        ui.label(status.now).classes("text-sm text-[#8f9590] text-center leading-5")
    with ui.column().classes("w-full gap-2"):
        with ui.row().classes("w-full items-center justify-between text-xs text-[#aab1ac]"):
            ui.label(f"{status.completed}/{status.total} {status.unit_label}(s)")
            ui.label(f"{round(status.ratio * 100)}%")
        progress_bar = ui.linear_progress(value=status.ratio, show_value=False).classes("w-full")
        progress_bar.props("instant-feedback rounded")

def _generation_loading_dialog(title: str, message: str | LoadingStatus) -> Any:
    with (
        ui.dialog().props(BLOCKING_DIALOG_PROPS) as loading_dialog,
        ui.card().classes(
            "entity-card rounded-2xl p-6 w-[min(560px,92vw)] items-center text-center gap-4"
        ),
    ):
        ui.spinner("dots", size="lg", color="primary")
        ui.label(title).classes("brand-type text-xl font-bold mt-3")
        if isinstance(message, LoadingStatus):
            _render_loading_status(message)
        else:
            ui.label(message).classes("text-sm text-[#8f9590] whitespace-pre-line leading-6")
    return loading_dialog


def _render_step_card(project_id: UUID, step: ProductionStep, counts: dict[str, int]) -> None:
    ready = _step_ready(step.key, counts)
    loading_title, loading_message = step_loading_copy(step.key, counts)
    status_text = "pronto" if ready else "pendente"
    status_classes = (
        "bg-emerald-950 text-emerald-200 border border-emerald-800"
        if ready
        else "bg-slate-800 text-slate-300 border border-slate-700"
    )
    with ui.card().classes(_card_classes("min-h-48")):
        with ui.row().classes("items-start justify-between w-full"):
            ui.icon(step.icon).classes("text-2xl text-cyan-300")
            ui.label(status_text).classes(f"text-xs px-2 py-1 rounded-md {status_classes}")
        ui.label(step.title).classes("text-lg font-semibold")
        ui.label(step.description).classes("text-sm text-slate-400 min-h-10")
        if step.key == "briefing":
            ui.button(
                "Criar via chat",
                icon="chat_bubble_outline",
                on_click=lambda: ui.navigate.to("/dashboard"),
            ).classes(_button_classes())
        else:
            loading_dialog = _generation_loading_dialog(loading_title, loading_message)
            ui.button(
                step.action_label,
                icon="play_arrow",
                on_click=lambda key=step.key, dialog=loading_dialog: _run_step(
                    project_id,
                    key,
                    dialog,
                ),
            ).classes(_button_classes())
