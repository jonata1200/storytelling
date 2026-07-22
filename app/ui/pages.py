# ruff: noqa: E501

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from nicegui import app as nicegui_app
from nicegui import background_tasks, ui
from sqlalchemy.ext.asyncio import AsyncSession

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
)
from app.storytelling.models import (
    Briefing,
    Scene,
    Script,
    StoryIdea,
)
from app.storytelling.schemas import BriefingCreate
from app.storytelling.service import (
    coerce_duration_minutes,
    create_briefing,
    create_story_idea_from_payload,
    generate_scenes_and_shots,
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
    home_sidebar as _home_sidebar,
)
from app.ui.layout.navigation import (
    save_avatar_file as _save_avatar_file,
)
from app.ui.layout.navigation import (
    studio_logo as _studio_logo,
)
from app.ui.layout.navigation import (
    theme_toggle as _theme_toggle,
)
from app.ui.layout.navigation import (
    user_avatar as _user_avatar,
)
from app.ui.layout.navigation import (
    workspace_header as _workspace_header,
)
from app.ui.layout.theme import apply_body_style as _body_style
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
from app.ui.project.assistant_panel import render_assistant_panel
from app.ui.project.cards import render_project_card
from app.ui.project.data import (
    latest as _latest,
)
from app.ui.project.data import (
    project_cards as _project_cards,
)
from app.ui.project.data import (
    project_summary as _project_summary,
)
from app.ui.project.data import (
    scalar_count as _scalar_count,
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
    _resume_initial_script_in_background,
    _set_project_ai_action_status,
)
from app.ui.project.workflows import (
    _log_ai_background_failure as _workflow_log_ai_background_failure,
)
from app.ui.routes.home_pages import register_home_pages
from app.ui.routes.project_workspace_page import register_project_workspace_pages
from app.ui.routes.settings_page import register_settings_page
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
    STEP_LOADING_COPY,
    ProductionStep,
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
    settings_tab_key as _settings_tab_key,
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
    _visual_reference_used_fallback as _visual_reference_used_fallback,
)
from app.ui.visual.helpers import (
    asset_url as _visual_asset_url,
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
from app.ui.workspace.assets_area import render_assets_area
from app.ui.workspace.rules import (
    first_available_workspace_section as _first_available_workspace_section,
)
from app.ui.workspace.rules import (
    step_ready as _step_ready,
)
from app.ui.workspace.rules import (
    workspace_section_access as _workspace_section_access,
)
from app.ui.workspace.script_area import render_script_area, save_script_from_ui
from app.ui.workspace.storyboard_video_area import render_storyboard_area, render_video_area

logger = logging.getLogger(__name__)
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

    if progress is not None:
        await progress("Vou escrever o roteiro cinematográfico a partir da ideia escolhida.")
    script = await generate_script(session, project_id, idea.id)
    if script is None:
        raise ValueError("não foi possível gerar roteiro")
    if progress is not None:
        await progress("Roteiro criado. Agora vou separar a história em cenas e planos.")
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        raise ValueError("não foi possível gerar cenas e planos")
    return script


def _retry_initial_script_from_ui(project_id: UUID, loading_dialog: Any) -> None:
    loading_dialog.open()
    background_tasks.create(
        _resume_initial_script_in_background(project_id),
        name=f"retry initial script {project_id}",
    )
    ui.timer(5.0, lambda: _reload_project_when_script_ready(project_id))
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
        scenes_count = await _scalar_count(session, Scene, project_id)
        if scenes_count == 0:
            await generate_scenes_and_shots(session, project_id, script.id)
            return "O roteiro já existia; criei as cenas e planos para ele.", True
        return (
            "Este projeto já tem roteiro e cenas. Posso ajudar a revisar ou ajustar a estrutura.",
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
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        return "O roteiro foi criado, mas não consegui gerar as cenas e planos.", True
    return "Roteiro criado e dividido em cenas e planos.", True


async def _create_project_from_form(
    form: dict[str, Any],
    *,
    generate_initial_script: bool = False,
    source_idea: dict[str, Any] | None = None,
) -> None:
    try:
        duration = coerce_duration_minutes(form["duration"])
        project_id: UUID
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
            await create_briefing(session, project.id, briefing)
            if generate_initial_script:
                await _set_project_ai_action_status(
                    session,
                    project.id,
                    status="queued",
                    message="A IA vai iniciar a criacao do roteiro inicial.",
                )
        if generate_initial_script:
            background_tasks.create(
                _generate_initial_script_in_background(
                    project_id,
                    dict(source_idea) if source_idea is not None else None,
                ),
                name=f"initial-script-{project_id}",
            )
        if generate_initial_script:
            message = f"Projeto criado. A IA já iniciou o roteiro de {duration:g} minutos."
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


async def _create_project_from_chat_prompt(prompt: str) -> None:
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
        "image_resolution": "1080x1920",
        "video_resolution": "1080x1920",
        "motion_intensity": 5,
        "image_model": get_settings().openrouter_image_model,
        "video_model": get_settings().openrouter_video_model,
    }
    await _create_project_from_form(form, generate_initial_script=True)


async def _create_project_from_idea(idea: dict[str, Any]) -> None:
    title = _clean_idea_title(idea.get("title"), "Ideia de storytelling")
    theme = str(idea.get("theme") or idea.get("premise") or title).strip()
    premise = str(idea.get("premise") or idea.get("hook") or theme).strip()
    genre = str(idea.get("genre") or "drama emocional").strip()
    emotion = str(idea.get("primary_emotion") or idea.get("final_emotion") or "curiosidade").strip()
    duration = coerce_duration_minutes(idea.get("duration_minutes"), DEFAULT_STORY_DURATION_MINUTES)
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
            "manter ritmo forte\n"
            "criar ganchos claros\n"
            f"adequar para {duration:g} minutos"
        ),
        "one_line_idea": _format_idea_payload_for_project(idea),
        "source_idea_payload": dict(idea),
        "content_type": "short_drama",
        "aspect_ratio": "9:16",
        "workflow_mode": "keyframes_i2v",
        "image_resolution": "1080x1920",
        "video_resolution": "1080x1920",
        "motion_intensity": 5,
        "image_model": get_settings().openrouter_image_model,
        "video_model": get_settings().openrouter_video_model,
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


def _generation_loading_dialog(title: str, message: str) -> Any:
    with ui.dialog().props(BLOCKING_DIALOG_PROPS) as loading_dialog, ui.card().classes(
        "entity-card rounded-2xl p-6 min-w-80 items-center text-center"
    ):
        ui.spinner("dots", size="lg", color="primary")
        ui.label(title).classes("brand-type text-xl font-bold mt-3")
        ui.label(message).classes("text-sm text-[#8f9590]")
    return loading_dialog


def _render_step_card(project_id: UUID, step: ProductionStep, counts: dict[str, int]) -> None:
    ready = _step_ready(step.key, counts)
    loading_title, loading_message = STEP_LOADING_COPY.get(
        step.key,
        ("Executando etapa", "A IA está trabalhando nesta etapa."),
    )
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


def _notify_ai_action_failure_once(project_id: UUID, summary: dict[str, Any]) -> None:
    ai_action = _project_ai_action(summary)
    if str(ai_action.get("status") or "") != "failed":
        return
    action = str(ai_action.get("action") or "ai_action")
    updated_at = str(ai_action.get("updated_at") or "")
    error = str(ai_action.get("error") or ai_action.get("message") or "").strip()
    notification_key = f"{project_id}:{action}:{updated_at}:{error}"
    store = nicegui_app.storage.user.setdefault("seen_ai_error_notifications", [])
    seen = [str(item) for item in store if isinstance(item, str)]
    if notification_key in seen:
        return
    seen.append(notification_key)
    nicegui_app.storage.user["seen_ai_error_notifications"] = seen[-80:]
    ui.notify(
        f"Falha na IA: {error or 'a IA não respondeu. Tente novamente.'}",
        color="negative",
        timeout=9000,
        close_button=True,
    )


def _sync_ai_action_events_to_chat(project_id: UUID, summary_or_action: dict[str, Any]) -> None:
    assistant_state.nicegui_app = nicegui_app
    ai_action = (
        _project_ai_action(summary_or_action)
        if "production_settings" in summary_or_action
        else summary_or_action
    )
    assistant_state.sync_ai_action_events_to_chat(project_id, ai_action)


def _assistant_panel(project_id: UUID, active: str, summary: dict[str, Any]) -> None:
    render_assistant_panel(
        project_id,
        active,
        summary,
        loading_dialog_factory=_generation_loading_dialog,
        project_ai_action=_project_ai_action,
        sync_ai_action_events_to_chat=_sync_ai_action_events_to_chat,
        notify_ai_action_failure_once=_notify_ai_action_failure_once,
    )

def _section_title(title: str, subtitle: str, action: str | None, callback: Any | None) -> None:
    with ui.row().classes("w-full items-end justify-between mb-2"):
        with ui.column().classes("gap-1"):
            ui.label(title).classes("brand-type text-3xl font-bold")
            ui.label(subtitle).classes("text-sm text-[#8e948f]")
        if action and callback:
            ui.button(action, icon="auto_awesome", on_click=callback).props(
                "unelevated no-caps"
            ).classes("acid-bg rounded-xl font-semibold")


def _project_ai_action(summary: dict[str, Any]) -> dict[str, Any]:
    settings = summary.get("production_settings")
    metadata = getattr(settings, "metadata_json", {}) or {}
    action = metadata.get("ai_action")
    return action if isinstance(action, dict) else {}


def _ai_action_is_stale(action: dict[str, Any], max_age_seconds: int = 120) -> bool:
    status = str(action.get("status") or "")
    if status not in {"queued", "running"}:
        return False
    updated_at = str(action.get("updated_at") or "").strip()
    if not updated_at:
        return True
    try:
        parsed = datetime.fromisoformat(updated_at)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    age = datetime.now(UTC) - parsed.astimezone(UTC)
    return age.total_seconds() > max_age_seconds


def _ordered_scenes(scenes: list[Any]) -> list[Any]:
    return sorted(scenes, key=lambda scene: int(getattr(scene, "scene_number", 0) or 0))


def _asset_url(storage_uri: str) -> str:
    return _visual_asset_url(storage_uri, get_settings().local_storage_path)


async def _save_script_from_ui(
    project_id: UUID,
    script_id: UUID,
    title: str,
    content: str,
) -> None:
    await save_script_from_ui(project_id, script_id, title, content)


def _render_script_area(project_id: UUID, summary: dict[str, Any]) -> None:
    render_script_area(
        project_id,
        summary,
        project_ai_action=_project_ai_action,
        ai_action_is_stale=_ai_action_is_stale,
        loading_dialog_factory=_generation_loading_dialog,
        retry_initial_script_from_ui=_retry_initial_script_from_ui,
        section_title=_section_title,
    )

def _render_assets_area(project_id: UUID, summary: dict[str, Any]) -> None:
    render_assets_area(
        project_id,
        summary,
        section_title=_section_title,
        loading_dialog_factory=_generation_loading_dialog,
    )

def _render_storyboard_area(project_id: UUID, summary: dict[str, Any]) -> None:
    render_storyboard_area(project_id, summary, section_title=_section_title)


def _render_video_area(project_id: UUID, summary: dict[str, Any]) -> None:
    render_video_area(project_id, summary, section_title=_section_title)

def register_ui_pages() -> None:
    register_home_pages(
        body_style=_body_style,
        project_cards=_project_cards,
        render_project_card=_render_project_card,
        create_project_from_chat_prompt=_create_project_from_chat_prompt,
        create_project_from_idea=_create_project_from_idea,
        delete_lab_idea_from_ui=_delete_lab_idea_from_ui,
        loading_dialog_factory=_generation_loading_dialog,
        clean_idea_title=_clean_idea_title,
        home_sidebar=_home_sidebar,
        studio_logo=_studio_logo,
        theme_toggle=_theme_toggle,
        user_avatar=_user_avatar,
    )
    register_settings_page(
        body_style=_body_style,
        settings_tab_key=_settings_tab_key,
        project_cards=_project_cards,
        home_sidebar=_home_sidebar,
        theme_toggle=_theme_toggle,
        user_avatar=_user_avatar,
        save_avatar_file=_save_avatar_file,
        purge_application_data_from_ui=_purge_application_data_from_ui,
        purge_all_ideas_from_ui=_purge_all_ideas_from_ui,
        purge_all_projects_from_ui=_purge_all_projects_from_ui,
    )
    register_project_workspace_pages(
        body_style=_body_style,
        project_summary=_project_summary,
        workspace_section_access=_workspace_section_access,
        first_available_workspace_section=_first_available_workspace_section,
        workspace_header=_workspace_header,
        render_script_area=_render_script_area,
        render_assets_area=_render_assets_area,
        render_storyboard_area=_render_storyboard_area,
        render_video_area=_render_video_area,
        assistant_panel=_assistant_panel,
    )
