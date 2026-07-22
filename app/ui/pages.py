# ruff: noqa: E501

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Request
from nicegui import app as nicegui_app
from nicegui import background_tasks, ui
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.preferences import save_preferences
from app.config.runtime_preferences import load_runtime_preferences
from app.config.settings import get_settings, normalize_openrouter_api_key
from app.database.session import AsyncSessionLocal
from app.generation.model_settings import (
    ensure_default_model_settings,
)
from app.generation.project_agent import classify_project_chat_action, handle_project_chat
from app.production.service import (
    update_production_settings,
)
from app.projects.models import Artifact, Project
from app.projects.schemas import ProjectCreate
from app.projects.service import (
    create_project,
)
from app.projects.versioning import create_artifact_version
from app.storytelling.idea_lab import (
    generate_freeform_ideas,
    load_generated_ideas,
    load_saved_ideas,
    replace_generated_ideas,
    save_idea,
)
from app.storytelling.models import (
    Briefing,
    Scene,
    Script,
    ScriptVersion,
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
from app.ui import assistant_state
from app.ui.assets_area import _entity_card as _entity_card
from app.ui.assets_area import render_assets_area
from app.ui.assistant_state import (
    load_assistant_messages as _load_assistant_messages,
)
from app.ui.assistant_state import (
    safe_client_navigation as _safe_client_navigation,
)
from app.ui.assistant_state import (
    safe_refresh as _safe_refresh,
)
from app.ui.assistant_state import (
    save_assistant_messages as _save_assistant_messages,
)
from app.ui.components import (
    button_classes as _button_classes,
)
from app.ui.components import (
    card_classes as _card_classes,
)
from app.ui.navigation import (
    home_sidebar as _home_sidebar,
)
from app.ui.navigation import (
    save_avatar_file as _save_avatar_file,
)
from app.ui.navigation import (
    studio_logo as _studio_logo,
)
from app.ui.navigation import (
    theme_toggle as _theme_toggle,
)
from app.ui.navigation import (
    user_avatar as _user_avatar,
)
from app.ui.navigation import (
    workspace_header as _workspace_header,
)
from app.ui.page_config import (
    BLOCKING_DIALOG_PROPS,
    DEFAULT_STORY_DURATION_MINUTES,
    IDEA_COUNT_OPTIONS,
    IDEA_GENRES,
    STEP_LOADING_COPY,
    STORY_DURATION_OPTIONS,
    UI_GENERATION_TIMEOUT_SECONDS,
    ProductionStep,
)
from app.ui.page_config import (
    PRODUCTION_STEPS as PAGE_PRODUCTION_STEPS,
)
from app.ui.page_config import (
    WORKSPACE_TABS as PAGE_WORKSPACE_TABS,
)
from app.ui.page_config import (
    clean_idea_title as _clean_idea_title,
)
from app.ui.page_config import (
    friendly_ai_error as _page_friendly_ai_error,
)
from app.ui.page_config import (
    settings_tab_key as _settings_tab_key,
)
from app.ui.production_steps import _run_step
from app.ui.project_actions import (
    _create_next_episode as _project_action_create_next_episode,
)
from app.ui.project_actions import (
    _delete_lab_idea_from_ui as _project_action_delete_lab_idea_from_ui,
)
from app.ui.project_actions import (
    _delete_project_from_ui as _project_action_delete_project_from_ui,
)
from app.ui.project_actions import (
    _purge_all_ideas_from_ui as _project_action_purge_all_ideas_from_ui,
)
from app.ui.project_actions import (
    _purge_all_projects_from_ui as _project_action_purge_all_projects_from_ui,
)
from app.ui.project_actions import (
    _purge_application_data_from_ui as _project_action_purge_application_data_from_ui,
)
from app.ui.project_actions import (
    _rename_project_from_ui as _project_action_rename_project_from_ui,
)
from app.ui.project_actions import (
    _save_model_setting as _project_action_save_model_setting,
)
from app.ui.project_actions import (
    _save_production_setup as _project_action_save_production_setup,
)
from app.ui.project_cards import render_project_card
from app.ui.project_data import (
    latest as _latest,
)
from app.ui.project_data import (
    project_cards as _project_cards,
)
from app.ui.project_data import (
    project_summary as _project_summary,
)
from app.ui.project_data import (
    scalar_count as _scalar_count,
)
from app.ui.project_text import (
    compact_project_title as _compact_project_title,
)
from app.ui.project_text import (
    format_idea_payload_for_project as _format_idea_payload_for_project,
)
from app.ui.project_workflows import (
    _generate_initial_script_in_background,
    _generate_missing_scenes_in_background,
    _reload_project_when_script_ready,
    _resume_initial_script_in_background,
    _set_project_ai_action_status,
)
from app.ui.project_workflows import (
    _log_ai_background_failure as _workflow_log_ai_background_failure,
)
from app.ui.storyboard_video_area import render_storyboard_area, render_video_area
from app.ui.theme import apply_body_style as _body_style
from app.ui.visual_actions import (  # noqa: F401
    _approve_all_visual_targets_from_ui as _approve_all_visual_targets_from_ui,
)
from app.ui.visual_actions import (  # noqa: F401
    _approve_visual_target_from_ui as _approve_visual_target_from_ui,
)
from app.ui.visual_actions import (
    _current_visual_batch_requests as _current_visual_batch_requests,
)
from app.ui.visual_actions import (
    _notify_visual_action as _notify_visual_action,
)
from app.ui.visual_actions import (  # noqa: F401
    _regenerate_visual_reference_from_ui as _regenerate_visual_reference_from_ui,
)
from app.ui.visual_actions import (  # noqa: F401
    _update_visual_prompt_from_ui as _update_visual_prompt_from_ui,
)
from app.ui.visual_actions import (  # noqa: F401
    _visual_batch_requests as _visual_batch_requests,
)
from app.ui.visual_actions import (
    _visual_fallback_notice as _visual_fallback_notice,
)
from app.ui.visual_actions import (
    _visual_library_cards_ready as _visual_library_cards_ready,
)
from app.ui.visual_actions import (
    _visual_reference_used_fallback as _visual_reference_used_fallback,
)
from app.ui.visual_helpers import (
    asset_url as _visual_asset_url,
)
from app.ui.visual_helpers import (  # noqa: F401
    visual_card_detail as _visual_card_detail,
)
from app.ui.visual_helpers import (  # noqa: F401
    visual_reference_asset as _visual_reference_asset,
)
from app.ui.visual_helpers import (  # noqa: F401
    visual_reference_views_for as _visual_reference_views_for,
)
from app.ui.visual_helpers import (  # noqa: F401
    visual_references_for as _visual_references_for,
)
from app.ui.workspace_rules import (
    first_available_workspace_section as _first_available_workspace_section,
)
from app.ui.workspace_rules import (
    step_ready as _step_ready,
)
from app.ui.workspace_rules import (
    workspace_section_access as _workspace_section_access,
)

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
            raise ValueError("nao foi possivel registrar a ideia selecionada")
    else:
        if progress is not None:
            await progress("Vou criar uma ideia base para orientar o roteiro.")
        generated_ideas = await generate_story_ideas(session, project_id)
        if not generated_ideas:
            raise ValueError("nao foi possivel gerar ideias iniciais")
        idea = generated_ideas[0]

    if progress is not None:
        await progress("Vou escrever o roteiro cinematografico a partir da ideia escolhida.")
    script = await generate_script(session, project_id, idea.id)
    if script is None:
        raise ValueError("nao foi possivel gerar roteiro")
    if progress is not None:
        await progress("Roteiro criado. Agora vou separar a historia em cenas e planos.")
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        raise ValueError("nao foi possivel gerar cenas e planos")
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
            "Este projeto ainda nao tem briefing. Crie o projeto pelo chat inicial ou preencha o briefing primeiro.",
            False,
        )

    script = await _latest(session, Script, project_id)
    if script is not None:
        scenes_count = await _scalar_count(session, Scene, project_id)
        if scenes_count == 0:
            await generate_scenes_and_shots(session, project_id, script.id)
            return "O roteiro ja existia; criei as cenas e planos para ele.", True
        return (
            "Este projeto ja tem roteiro e cenas. Posso ajudar a revisar ou ajustar a estrutura.",
            False,
        )

    idea = await _latest(session, StoryIdea, project_id)
    if idea is None:
        ideas = await generate_story_ideas(session, project_id)
        if not ideas:
            return "Nao consegui gerar uma ideia base para este projeto.", False
        idea = ideas[0]

    script = await generate_script(session, project_id, idea.id)
    if script is None:
        return "Nao consegui gerar o roteiro para este projeto.", False
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        return "O roteiro foi criado, mas nao consegui gerar as cenas e planos.", True
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
            message = f"Projeto criado. A IA ja iniciou o roteiro de {duration:g} minutos."
        else:
            message = "Projeto criado com briefing inicial."
        ui.notify(message, color="positive")
        if generate_initial_script:
            destination = f"/projects/{project_id}/script"
        else:
            destination = f"/projects/{project_id}"
        ui.navigate.to(destination)
    except Exception as exc:
        ui.notify(f"Nao foi possivel criar o projeto: {exc}", color="negative")


async def _create_project_from_chat_prompt(prompt: str) -> None:
    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        ui.notify("Descreva a ideia ou cole um roteiro antes de criar o projeto.", color="warning")
        return
    form = {
        "title": _compact_project_title(cleaned_prompt),
        "description": cleaned_prompt[:240],
        "theme": cleaned_prompt[:220],
        "audience": "publico geral",
        "genre": "drama emocional",
        "emotion": "curiosidade",
        "intensity": 8,
        "ending": "final com revelacao afetiva",
        "duration": DEFAULT_STORY_DURATION_MINUTES,
        "visual_style": "cinematico realista vertical",
        "objective": (
            f"reter audiencia com uma historia completa de "
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
        "audience": "publico geral",
        "genre": genre,
        "emotion": emotion,
        "intensity": 8,
        "ending": "final com payoff emocional",
        "duration": duration,
        "visual_style": "cinematico realista vertical",
        "objective": f"desenvolver uma historia completa de {duration:g} minutos",
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
        ("Executando etapa", "A IA esta trabalhando nesta etapa."),
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
        f"Falha na IA: {error or 'a IA nao respondeu. Tente novamente.'}",
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
    prompts = {
        "script": "Peça ajustes de tom, diálogo ou estrutura.",
        "assets": "Descreva um personagem, local ou objeto.",
        "storyboard": "Diga ao diretor o que enquadrar.",
        "video": "Descreva movimento, câmera ou ritmo.",
    }
    assistant_suggestions = {
        "script": (
            "Sugestões que posso ajudar agora: revisar a estrutura do roteiro, "
            "fortalecer o gancho inicial ou ajustar diálogos."
        ),
        "assets": (
            "Sugestões que posso ajudar agora: criar personagens, locais e objetos "
            "a partir do roteiro, aprofundar perfis visuais ou gerar variações "
            "mantendo a continuidade do projeto."
        ),
        "storyboard": (
            "Sugestões que posso ajudar agora: criar o storyboard a partir do roteiro, "
            "melhorar enquadramentos, ajustar ritmo visual ou revisar continuidade entre cenas."
        ),
        "video": (
            "Sugestões que posso ajudar agora: criar clipes a partir do storyboard, "
            "orientar movimento de câmera, ajustar ritmo ou propor variações de montagem."
        ),
    }
    chat_loading_copy = {
        "generate_ideas": STEP_LOADING_COPY["ideas"],
        "generate_script": STEP_LOADING_COPY["script"],
        "revise_script": ("Revisando roteiro", "A IA esta aplicando ajustes no roteiro."),
        "generate_assets": STEP_LOADING_COPY["visual"],
        "approve_visual_prompt": (
            "Gerando imagens",
            "A IA esta criando imagens a partir dos prompts aprovados.",
        ),
        "generate_storyboard": STEP_LOADING_COPY["storyboard"],
        "generate_video": (
            "Gerando clipes",
            "A IA esta criando clipes a partir dos prompts aprovados.",
        ),
        "generate_finalization": STEP_LOADING_COPY["finalization"],
        "run_quality": STEP_LOADING_COPY["quality"],
    }
    action_loading_dialogs = {
        action: _generation_loading_dialog(title, message)
        for action, (title, message) in chat_loading_copy.items()
    }
    _sync_ai_action_events_to_chat(project_id, _project_ai_action(summary))
    _notify_ai_action_failure_once(project_id, summary)
    messages = _load_assistant_messages(project_id, active, assistant_suggestions)

    with ui.element("aside").classes(
        "right-assistant flex flex-col min-h-0 mt-0 gap-4 sticky top-0 self-start"
    ):
        with ui.element("div").classes(
            "flex w-full items-center justify-between mt-0 pt-0 shrink-0"
        ):
            with ui.element("div").classes("flex items-center gap-2"):
                ui.icon("auto_awesome").classes("acid")
                ui.label("Diretor IA").classes("font-semibold")
            ui.badge("online").classes("bg-[#26301f] text-white")

        @ui.refreshable
        def conversation() -> None:
            with ui.column().classes("w-full gap-3"):
                for item in messages:
                    sent = item["role"] == "user"
                    pending = item["role"] == "assistant_pending"
                    with ui.row().classes(f"w-full {'justify-end' if sent else 'justify-start'}"):
                        if pending:
                            with ui.row().classes(
                                "assistant-chat-bubble glass text-[#c8ccc8] rounded-2xl "
                                "rounded-bl-sm px-4 py-3 text-sm leading-5 max-w-full "
                                "items-center gap-2"
                            ):
                                ui.spinner("dots", size="sm", color="primary")
                                ui.label(item["content"])
                        else:
                            ui.label(item["content"]).classes(
                                "assistant-chat-bubble w-fit rounded-2xl px-4 py-3 text-sm leading-5 "
                                + ("max-w-[88%] " if sent else "max-w-full ")
                                + (
                                    "acid-bg assistant-chat-user-bubble rounded-br-sm"
                                    if sent
                                    else "glass text-[#c8ccc8] rounded-bl-sm"
                                )
                            )

        with ui.column().classes(
            "assistant-chat-messages w-full flex-1 min-h-0 overflow-y-auto"
        ):
            conversation()

        async def send_message(text: str | None = None) -> None:
            client = prompt.client
            user_message = (text or prompt.value or "").strip()
            if not user_message:
                return
            messages.append({"role": "user", "content": user_message})
            pending_message = {
                "role": "assistant_pending",
                "content": "Diretor IA esta buscando a melhor resposta...",
            }
            messages.append(pending_message)
            _save_assistant_messages(project_id, messages)
            prompt.value = ""
            _safe_refresh(conversation)
            should_reload = False
            predicted_action = classify_project_chat_action(user_message, active)
            loading_dialog = action_loading_dialogs.get(predicted_action)
            if loading_dialog is not None:
                loading_dialog.open()

            async def report_progress(content: str) -> None:
                progress_message = content.strip()
                if not progress_message:
                    return
                pending_message["content"] = progress_message
                _save_assistant_messages(project_id, messages)
                _safe_refresh(conversation)
                await asyncio.sleep(0)

            try:
                async with AsyncSessionLocal() as session:
                    result = await handle_project_chat(
                        session,
                        project_id,
                        active,
                        user_message,
                        [item for item in messages if item["role"] != "assistant_pending"],
                        progress=report_progress,
                    )
                    response = result.message
                    should_reload = result.changed
            except Exception as exc:
                logger.exception(
                    "Nao foi possivel responder ao chat do projeto %s na etapa %s",
                    project_id,
                    active,
                )
                response = f"Não consegui responder agora ({type(exc).__name__}). Tente novamente."
            if loading_dialog is not None:
                loading_dialog.close()
            if pending_message in messages:
                messages.remove(pending_message)
            messages.append({"role": "assistant", "content": response})
            _save_assistant_messages(project_id, messages)
            if should_reload:
                _safe_client_navigation(client)
                return
            _safe_refresh(conversation)

        with ui.row().classes("w-full items-end gap-2 shrink-0"):
            prompt = (
                ui.textarea(placeholder=prompts[active])
                .props("outlined dense autogrow rows=1")
                .classes("flex-1 assistant-chat-input")
            )
            prompt.on(
                "keydown",
                lambda: send_message(),
                js_handler="""(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        emit();
                    }
                }""",
            )
            ui.button(
                icon="arrow_upward",
                on_click=send_message,
            ).props("round unelevated").classes("acid-bg shrink-0 mb-1")


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
    try:
        clean_title = title.strip()
        clean_content = content.strip()
        if not clean_title:
            raise ValueError("Informe um titulo para o roteiro.")
        if not clean_content:
            raise ValueError("O roteiro nao pode ficar vazio.")

        async with AsyncSessionLocal() as session:
            script = await session.get(Script, script_id)
            if script is None or script.project_id != project_id:
                raise ValueError("Roteiro nao encontrado.")
            artifact = await session.get(Artifact, script.artifact_id)
            if artifact is None:
                raise ValueError("Artefato do roteiro nao encontrado.")

            script.title = clean_title[:220]
            script.content = clean_content
            script.word_count = len(clean_content.split())
            payload = {
                "title": script.title,
                "language": script.language,
                "target_duration_seconds": script.target_duration_seconds,
                "word_count": script.word_count,
                "content": script.content,
            }
            artifact.name = script.title
            await create_artifact_version(
                session,
                artifact,
                payload,
                change_note="Script edited manually in UI",
            )
            session.add(
                ScriptVersion(
                    script_id=script.id,
                    version_number=artifact.current_version,
                    content=script.content,
                    word_count=script.word_count,
                    payload=payload,
                )
            )
            await session.commit()
        ui.notify("Roteiro salvo.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        ui.notify(f"Nao consegui salvar o roteiro: {exc}", color="negative")


def _render_script_area(project_id: UUID, summary: dict[str, Any]) -> None:
    script = summary["script"]
    ai_action = _project_ai_action(summary)
    ai_status = str(ai_action.get("status") or "")
    ai_action_name = str(ai_action.get("action") or "")
    missing_scenes = script is not None and not summary["scenes"]
    scene_generation_failed = ai_action_name == "create_script_scenes" and ai_status == "failed"
    should_recover_missing_scenes = (
        missing_scenes and ai_status not in {"queued", "running"} and not scene_generation_failed
    )
    should_resume_stale_script = (
        script is None
        and ai_status in {"queued", "running"}
        and _ai_action_is_stale(ai_action)
    )
    if should_recover_missing_scenes:
        background_tasks.create(
            _generate_missing_scenes_in_background(project_id, script.id),
            name=f"generate missing scenes {project_id}",
        )
    if should_resume_stale_script:
        background_tasks.create(
            _resume_initial_script_in_background(project_id),
            name=f"resume initial script {project_id}",
        )
    generation_in_progress = (
        ai_status in {"queued", "running"}
        or should_recover_missing_scenes
        or should_resume_stale_script
    )
    if generation_in_progress:
        loading_title = (
            "Gerando cenas"
            if missing_scenes
            else (
                "Retomando roteiro"
                if should_resume_stale_script
                else STEP_LOADING_COPY["script"][0]
            )
        )
        loading_message = (
            "A IA esta criando cenas e planos para o roteiro."
            if missing_scenes
            else str(
                ai_action.get("message")
                or "A IA esta desenvolvendo o roteiro com base na ideia."
            )
        )
        loading_dialog = _generation_loading_dialog(loading_title, loading_message)
        loading_dialog.open()
        ui.timer(5.0, lambda: _reload_project_when_script_ready(project_id))
    edit_dialog = None
    if script is not None:
        with ui.dialog().props(BLOCKING_DIALOG_PROPS) as edit_dialog, ui.card().classes(
            "entity-card rounded-2xl p-6 w-[min(1040px,94vw)] h-[min(860px,92vh)] "
            "max-h-[92vh] flex flex-col"
        ):
            ui.label("Editar roteiro").classes("brand-type text-2xl font-bold shrink-0")
            title_input = ui.input("Titulo", value=script.title).props("outlined").classes("w-full")
            content_input = ui.textarea("Conteudo do roteiro", value=script.content).props(
                "outlined"
            ).classes("script-editor-textarea w-full flex-1 min-h-0 font-mono text-sm")
            with ui.row().classes("w-full justify-end gap-2 shrink-0"):
                ui.button("Cancelar", on_click=edit_dialog.close).props("flat no-caps")
                ui.button(
                    "Salvar",
                    icon="save",
                    on_click=lambda: _save_script_from_ui(
                        project_id,
                        script.id,
                        str(title_input.value or ""),
                        str(content_input.value or ""),
                    ),
                ).props("unelevated no-caps").classes("acid-bg rounded-xl font-semibold")
    _section_title(
        "Roteiro",
        "Edite e revise o roteiro cinematografico que orienta as proximas etapas.",
        "Editar roteiro" if edit_dialog is not None else None,
        edit_dialog.open if edit_dialog is not None else None,
    )
    with ui.row().classes("w-full gap-4 items-start"):
        with ui.column().classes("flex-1 gap-4"):
            if script is None and ai_status == "failed":
                retry_loading_dialog = _generation_loading_dialog(
                    "Retomando roteiro",
                    "A IA esta tentando criar o roteiro inicial novamente.",
                )

                def retry_initial_script() -> None:
                    _retry_initial_script_from_ui(project_id, retry_loading_dialog)

                with ui.element("div").classes(
                    "border border-red-900 bg-red-950/40 rounded-2xl p-4 text-red-100"
                ):
                    ui.label("A IA nao conseguiu criar o roteiro inicial.").classes(
                        "font-semibold"
                    )
                    ui.label(str(ai_action.get("error") or ai_action.get("message") or "")).classes(
                        "text-sm opacity-80"
                    )
                    ui.button(
                        "Tentar novamente",
                        icon="refresh",
                        on_click=retry_initial_script,
                    ).props("unelevated no-caps").classes("acid-bg rounded-xl mt-3")
            with ui.element("div").classes("entity-card rounded-2xl p-7 min-h-[640px] w-full"):
                ui.label(script.title if script else "Seu roteiro começa aqui").classes(
                    "brand-type text-2xl font-bold mb-5"
                )
                content = (
                    script.content
                    if script
                    else "A IA esta desenvolvendo o roteiro com base na ideia do projeto."
                )
                ui.label(content).classes("whitespace-pre-wrap leading-8 text-[#d9dcd9]")


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
    @ui.page("/dashboard", response_timeout=15)
    async def dashboard() -> None:
        _body_style()
        projects = await _project_cards()
        _home_sidebar("create")
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full px-5 md:px-10 lg:px-14 py-6 gap-9"):
                with ui.row().classes(
                    "w-full max-w-6xl mx-auto items-center justify-between min-h-14"
                ):
                    _studio_logo()
                    with ui.row().classes("items-center gap-3"):
                        _theme_toggle()
                        _user_avatar(size="48px")
                with ui.column().classes("w-full max-w-4xl mx-auto items-center text-center gap-4"):
                    with ui.element("div").classes(
                        "chat-shell glass rounded-3xl p-4 w-full min-h-[240px] flex flex-col"
                    ):
                        idea = (
                            ui.textarea(
                                placeholder="Descreva sua história, cole um roteiro ou peça uma ideia..."
                            )
                            .props("borderless autogrow input-style='min-height:140px'")
                            .classes("w-full text-lg flex-1 text-left")
                        )
                        with ui.row().classes("w-full items-center px-2 pb-1 gap-2"):
                            ui.space()
                            ui.button(
                                icon="arrow_upward",
                                on_click=lambda: _create_project_from_chat_prompt(
                                    str(idea.value or "")
                                ),
                            ).props("round unelevated").classes("acid-bg")
                with (
                    ui.column().props("id=projects").classes("w-full max-w-6xl mx-auto gap-4 pt-3")
                ):
                    with ui.row().classes("w-full items-center justify-between"):
                        with ui.column().classes("gap-0"):
                            ui.label("Projetos recentes").classes(
                                "brand-type text-2xl md:text-3xl font-bold"
                            )
                            ui.label("Continue de onde parou ou comece uma nova produção.").classes(
                                "text-sm text-[#7f8580]"
                            )
                    if not projects:
                        with (
                            ui.element("div")
                            .classes(
                                "w-full border border-dashed border-[#363b36] rounded-2xl min-h-48 flex flex-col items-center justify-center cursor-pointer text-[#969c97] bg-[#0d100e]"
                            )
                            .on("click", lambda: ui.navigate.to("/dashboard"))
                        ):
                            ui.icon("add_circle_outline").classes("text-4xl acid")
                            ui.label("Crie seu primeiro projeto").classes(
                                "mt-3 text-lg font-semibold text-[#d7dbd7]"
                            )
                            ui.label(
                                "Sua história, personagens e storyboards aparecerão aqui."
                            ).classes("mt-1 text-sm text-[#747a75]")
                    else:
                        with ui.grid().classes(
                            "w-full grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
                        ):
                            for project in projects:
                                _render_project_card(project, "/dashboard")
                            with (
                                ui.element("div")
                                .classes(
                                    "border border-dashed border-[#363b36] rounded-2xl min-h-52 flex flex-col items-center justify-center cursor-pointer text-[#969c97]"
                                )
                                .on("click", lambda: ui.navigate.to("/dashboard"))
                            ):
                                ui.icon("add_circle_outline").classes("text-4xl acid")
                                ui.label("Criar novo projeto").classes("mt-2 font-semibold")

    @ui.page("/projects", response_timeout=15)
    async def projects_page() -> None:
        _body_style()
        projects = await _project_cards()
        _home_sidebar("projects")
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full max-w-6xl mx-auto px-6 py-8 gap-7"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-1"):
                        ui.label("Projetos").classes("brand-type text-4xl font-bold")
                        ui.label("Acompanhe e continue suas produções de vídeo.").classes(
                            "text-[#8f9590]"
                        )
                    with ui.row().classes("items-center gap-2"):
                        _theme_toggle()
                        ui.button(
                            "Novo projeto",
                            icon="add",
                            on_click=lambda: ui.navigate.to("/dashboard"),
                        ).props("unelevated no-caps").classes("acid-bg rounded-xl")
                if not projects:
                    with ui.element("div").classes(
                        "w-full border border-dashed border-[#363b36] rounded-2xl min-h-64 flex flex-col items-center justify-center text-[#969c97]"
                    ):
                        ui.icon("folder_open").classes("text-5xl")
                        ui.label("Nenhum projeto criado ainda.").classes(
                            "mt-3 text-lg font-semibold"
                        )
                        ui.button(
                            "Começar uma criação",
                            icon="auto_awesome",
                            on_click=lambda: ui.navigate.to("/dashboard"),
                        ).props("flat no-caps").classes("acid mt-2")
                else:
                    with ui.grid().classes(
                        "w-full grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
                    ):
                        for project in projects:
                            _render_project_card(project, "/projects")

    @ui.page("/", response_timeout=15)
    @ui.page("/ideas", response_timeout=15)
    async def ideas_page() -> None:
        _body_style()
        _home_sidebar("ideas")
        saved_ideas = load_saved_ideas()
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full max-w-6xl mx-auto px-6 py-8 gap-7"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-1"):
                        with ui.row().classes("items-center gap-3"):
                            ui.icon("lightbulb").classes("text-4xl acid")
                            ui.label("Laboratório de Ideias").classes(
                                "brand-type text-4xl font-bold"
                            )
                        ui.label(
                            "Explore histórias livremente, sem criar um projeto de vídeo."
                        ).classes("text-[#8f9590]")
                    _theme_toggle()

                with ui.element("div").classes("hidden"):
                    _ = (
                        ui.textarea(
                            "Sobre o que você quer contar?",
                            placeholder="Ex.: uma astronauta encontra uma mensagem enviada por ela mesma...",
                        )
                        .props("outlined autogrow stack-label")
                        .classes("hidden")
                    )
                    with ui.grid().classes("hidden"):
                        _ = ui.select(
                            [
                                "Drama",
                                "Ficção científica",
                                "Suspense",
                                "Comédia",
                                "Terror",
                                "Romance",
                            ],
                            label="Gênero",
                            value="Drama",
                        ).props("outlined")
                        _ = ui.select(
                            [
                                "Esperança",
                                "Curiosidade",
                                "Tensão",
                                "Alegria",
                                "Melancolia",
                                "Surpresa",
                            ],
                            label="Emoção principal",
                            value="Esperança",
                        ).props("outlined")

                    loading_title, loading_message = STEP_LOADING_COPY["ideas"]
                    loading_dialog = _generation_loading_dialog(
                        loading_title,
                        loading_message,
                    )

                    async def generate() -> None:
                        loading_dialog.open()
                        try:
                            generated = await asyncio.wait_for(
                                generate_freeform_ideas(
                                    "",
                                    count=int(idea_count_select.value or 10),
                                    genre=str(genre_select.value or ""),
                                    target_duration_minutes=coerce_duration_minutes(
                                        duration_select.value
                                    ),
                                ),
                                timeout=UI_GENERATION_TIMEOUT_SECONDS,
                            )
                            replace_generated_ideas([])
                            for generated_idea in generated:
                                saved = save_idea(generated_idea)
                                saved_ideas[:] = [
                                    existing
                                    for existing in saved_ideas
                                    if existing.get("id") != saved["id"]
                                ]
                                saved_ideas.insert(0, saved)
                            saved_results.refresh()
                            ui.notify(
                                f"{len(generated)} ideia(s) gerada(s) e salva(s).",
                                color="positive",
                            )
                        except TimeoutError:
                            ui.notify(
                                "A geracao demorou demais. Tente novamente ou use mock.",
                                color="warning",
                            )
                        except Exception as exc:
                            ui.notify(f"Não foi possível gerar ideias: {exc}", color="negative")
                        finally:
                            loading_dialog.close()

                with ui.column().classes("w-full items-center gap-4 py-8"):
                    with ui.row().classes("w-full max-w-2xl gap-3 items-end justify-center"):
                        genre_select = (
                            ui.select(IDEA_GENRES, label="Gênero", value=IDEA_GENRES[0])
                            .props("outlined")
                            .classes("flex-1 min-w-64")
                        )
                        duration_select = (
                            ui.select(
                                STORY_DURATION_OPTIONS,
                                label="Duração",
                                value=int(DEFAULT_STORY_DURATION_MINUTES),
                            )
                            .props("outlined suffix='min'")
                            .classes("w-36")
                        )
                        idea_count_select = (
                            ui.select(
                                IDEA_COUNT_OPTIONS,
                                label="Quantidade",
                                value=10,
                            )
                            .props("outlined suffix='ideias'")
                            .classes("w-40")
                        )
                    ui.button(
                        "Gerar ideias",
                        icon="auto_awesome",
                        on_click=generate,
                    ).props("unelevated no-caps size=lg").classes(
                        "acid-bg rounded-2xl px-10 py-5 text-lg font-bold"
                    )

                async def delete_saved(idea_id: str) -> None:
                    deleted = await _delete_lab_idea_from_ui(idea_id, "saved")
                    if not deleted:
                        return
                    saved_ideas[:] = [
                        idea for idea in saved_ideas if str(idea.get("id")) != idea_id
                    ]
                    saved_results.refresh()
                    ui.notify("Ideia apagada definitivamente.", color="warning")

                @ui.refreshable
                def saved_results() -> None:
                    ui.label("Ideias salvas").classes("brand-type text-2xl font-bold")
                    if not saved_ideas:
                        ui.label("Nenhuma ideia salva ainda.").classes("text-sm text-[#777d78]")
                        return
                    with ui.grid().classes("w-full grid-cols-1 lg:grid-cols-3 gap-4"):
                        for idea in saved_ideas:
                            with ui.element("article").classes(
                                "entity-card rounded-2xl p-5 flex flex-col min-h-80"
                            ):
                                ui.label(
                                    _clean_idea_title(idea.get("title"), "Historia sem titulo")
                                ).classes(
                                    "brand-type text-2xl font-bold"
                                )
                                with ui.row().classes("gap-2 mt-3 flex-wrap"):
                                    ui.label(str(idea.get("genre") or "Genero sugerido")).classes(
                                        "idea-badge-genre rounded-md px-2 py-0.5 text-xs font-medium"
                                    )
                                    ui.label(
                                        str(idea.get("primary_emotion") or "Emocao sugerida")
                                    ).classes(
                                        "idea-badge-emotion rounded-md px-2 py-0.5 text-xs font-medium"
                                    )
                                    ui.label(
                                        f"{coerce_duration_minutes(idea.get('duration_minutes')):g} min"
                                    ).classes(
                                        "idea-badge-duration rounded-md px-2 py-0.5 text-xs font-medium"
                                    )
                                if idea.get("theme"):
                                    ui.label(f"Tema: {idea['theme']}").classes(
                                        "text-xs text-[#9aa29b] mt-3"
                                    )
                                ui.label(str(idea.get("hook") or "")).classes(
                                    "text-sm text-[#d4d8d4] mt-3 font-medium"
                                )
                                ui.label(str(idea.get("premise") or "")).classes(
                                    "text-sm text-[#8d938e] mt-3 leading-6"
                                )
                                ui.space()
                                with ui.row().classes("gap-2 mt-4"):
                                    saved_idea_id = str(idea.get("id"))
                                    ui.button(
                                        "Descartar",
                                        icon="delete",
                                        on_click=lambda idea_id=saved_idea_id: delete_saved(idea_id),
                                    ).props("flat no-caps").classes("text-red-300")
                                    ui.button(
                                        "Desenvolver",
                                        icon="arrow_forward",
                                        on_click=lambda item=idea: _create_project_from_idea(item),
                                    ).props("flat no-caps").classes("acid")

                saved_results()

    @ui.page("/settings", response_timeout=15)
    async def settings_page(request: Request) -> None:
        _body_style()
        current = get_settings()
        active_settings_tab = _settings_tab_key(request.query_params.get("tab"))
        saved_idea_count = len(load_saved_ideas())
        generated_idea_count = len(load_generated_ideas())
        project_count = len(await _project_cards())
        _home_sidebar("settings")
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full max-w-5xl mx-auto px-6 py-8 gap-7"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-1"):
                        ui.label("Configurações").classes("brand-type text-4xl font-bold")
                        ui.label("Gerencie seu perfil e os modelos usados pelo estúdio.").classes(
                            "text-[#8f9590]"
                        )
                    _theme_toggle()

                with (
                    ui.tabs()
                    .classes("text-[#989e99]")
                    .props("no-caps active-color=primary indicator-color=primary") as settings_tabs
                ):
                    profile_tab = ui.tab("Perfil", icon="person")
                    ai_tab = ui.tab("Inteligência artificial", icon="auto_awesome")
                    data_tab = ui.tab("Dados", icon="delete_sweep")
                initial_settings_tab = {"profile": profile_tab, "ai": ai_tab, "data": data_tab}[
                    active_settings_tab
                ]
                with ui.tab_panels(settings_tabs, value=initial_settings_tab).classes(
                    "w-full bg-transparent p-0"
                ):
                    with ui.tab_panel(profile_tab).classes("px-0"):
                        with ui.element("div").classes("entity-card rounded-2xl p-6"):
                            ui.label("Dados do usuário").classes("text-xl font-semibold")
                            ui.label("Informações exibidas no seu espaço de trabalho.").classes(
                                "text-sm text-[#858b86] mb-4"
                            )

                            @ui.refreshable
                            def avatar_preview() -> None:
                                with ui.row().classes("items-center gap-4 mb-5"):
                                    photo_avatar = _user_avatar(size="80px", navigate=False)
                                    photo_avatar.on(
                                        "click",
                                        lambda: ui.run_javascript(
                                            "document.querySelector('#avatar-upload input[type=file]').click()"
                                        ),
                                    ).tooltip("Clique para alterar a foto")
                                    with ui.column().classes("gap-1"):
                                        ui.label("Foto do perfil").classes("font-semibold")
                                        ui.label("JPG, PNG ou WebP · máximo de 5 MB").classes(
                                            "text-xs text-[#7f8580]"
                                        )
                                        ui.label("Clique na foto para alterar").classes(
                                            "text-xs acid"
                                        )

                            avatar_preview()

                            async def upload_avatar(event: Any) -> None:
                                suffix = Path(event.file.name).suffix.lower()
                                if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                                    ui.notify("Formato de imagem não permitido.", color="negative")
                                    return
                                content = await event.file.read()
                                target = await asyncio.to_thread(
                                    _save_avatar_file, event.file.name, content
                                )
                                save_preferences({"USER_AVATAR_PATH": target.as_posix()})
                                avatar_preview.refresh()
                                ui.notify("Foto do perfil atualizada.", color="positive")

                            ui.upload(
                                label="Escolher foto",
                                on_upload=upload_avatar,
                                on_rejected=lambda: ui.notify(
                                    "A imagem deve ter no máximo 5 MB.", color="warning"
                                ),
                                auto_upload=True,
                                max_file_size=5_000_000,
                            ).props("id=avatar-upload accept=.jpg,.jpeg,.png,.webp").classes(
                                "hidden"
                            )

                            display_name = (
                                ui.input("Nome", value=current.user_display_name)
                                .props("outlined")
                                .classes("w-full")
                            )
                            email = (
                                ui.input("E-mail", value=current.user_email)
                                .props("outlined type=email")
                                .classes("w-full mt-3")
                            )

                            def save_profile() -> None:
                                save_preferences(
                                    {
                                        "USER_DISPLAY_NAME": display_name.value or "",
                                        "USER_EMAIL": email.value or "",
                                    }
                                )
                                ui.notify("Perfil salvo.", color="positive")

                            ui.button("Salvar perfil", icon="save", on_click=save_profile).props(
                                "unelevated no-caps"
                            ).classes("acid-bg rounded-xl mt-5")
                    with ui.tab_panel(ai_tab).classes("px-0"):
                        with ui.element("div").classes("entity-card rounded-2xl p-6"):
                            ui.label("OpenRouter").classes("text-xl font-semibold")
                            ui.label(
                                "Conecte sua conta e escolha modelos diferentes para cada mídia."
                            ).classes("text-sm text-[#858b86] mb-4")
                            saved_api_key = load_runtime_preferences().get(
                                "openrouter_api_key", ""
                            ).strip()
                            saved_api_key_invalid = bool(
                                saved_api_key
                                and normalize_openrouter_api_key(saved_api_key) is None
                            )
                            if current.openrouter_api_key:
                                ui.label("Chave OpenRouter valida configurada.").classes(
                                    "text-xs px-2 py-1 rounded-md bg-emerald-950 text-emerald-200 border border-emerald-800"
                                )
                            elif saved_api_key_invalid:
                                ui.label(
                                    "A chave OpenRouter salva e invalida. Cole uma chave iniciada por sk-or-."
                                ).classes(
                                    "text-xs px-2 py-1 rounded-md bg-red-950 text-red-200 border border-red-800"
                                )
                            else:
                                ui.label(
                                    "Sem chave OpenRouter valida: modelos reais de imagem, video e texto nao serao chamados."
                                ).classes(
                                    "text-xs px-2 py-1 rounded-md bg-amber-950 text-amber-200 border border-amber-800"
                                )
                            api_key = (
                                ui.input(
                                    "Chave da API",
                                    placeholder=(
                                        "Chave configurada — digite apenas para substituir"
                                        if current.openrouter_api_key
                                        else "sk-or-v1-..."
                                    ),
                                    password=True,
                                    password_toggle_button=True,
                                )
                                .props("outlined stack-label")
                                .classes("w-full")
                            )
                            text_model = (
                                ui.input(
                                    "Modelo de texto",
                                    value=current.openrouter_default_model,
                                    placeholder="openai/gpt-4o-mini",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            image_model = (
                                ui.input(
                                    "Modelo de imagem",
                                    value=current.openrouter_image_model,
                                    placeholder="google/gemini-2.5-flash-image",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            video_model = (
                                ui.input(
                                    "Modelo de video",
                                    value=current.openrouter_video_model,
                                    placeholder="google/veo-3.1",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )

                            def save_ai() -> None:
                                typed_api_key = str(api_key.value or "").strip()
                                values = {
                                    "OPENROUTER_DEFAULT_MODEL": text_model.value or "",
                                    "OPENROUTER_IMAGE_MODEL": image_model.value or "",
                                    "OPENROUTER_VIDEO_MODEL": video_model.value or "",
                                }
                                if typed_api_key:
                                    normalized_key = normalize_openrouter_api_key(typed_api_key)
                                    if normalized_key is None:
                                        ui.notify(
                                            "Chave OpenRouter invalida. Ela deve comecar com sk-or-.",
                                            color="negative",
                                        )
                                        return
                                    values["OPENROUTER_API_KEY"] = normalized_key
                                elif saved_api_key_invalid:
                                    values["OPENROUTER_API_KEY"] = ""
                                save_preferences(values)
                                ui.notify("Configurações de IA salvas.", color="positive")

                            with ui.row().classes("mt-5 gap-3"):
                                ui.button(
                                    "Salvar configurações", icon="save", on_click=save_ai
                                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
                    with ui.tab_panel(data_tab).classes("px-0"):
                        with ui.element("div").classes("entity-card rounded-2xl p-6"):
                            ui.label("Gerenciamento de dados").classes("text-xl font-semibold")
                            ui.label(
                                "Ações destrutivas para limpar ideias e projetos do estúdio."
                            ).classes("text-sm text-[#858b86] mb-4")

                            async def confirm_purge_ideas() -> None:
                                ideas_dialog.close()
                                await _purge_all_ideas_from_ui()

                            async def confirm_purge_projects() -> None:
                                projects_dialog.close()
                                await _purge_all_projects_from_ui()

                            with ui.dialog() as ideas_dialog, ui.card().classes(
                                "entity-card rounded-2xl p-6 min-w-96"
                            ):
                                ui.label("Apagar todas as ideias?").classes(
                                    "text-xl font-semibold"
                                )
                                ui.label(
                                    "Isso remove ideias salvas, ideias geradas e registros "
                                    "de ideias no banco. Projetos serao mantidos, mas "
                                    "conteudos derivados das ideias serao removidos."
                                ).classes("text-sm text-[#858b86]")
                                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                                    ui.button("Cancelar", on_click=ideas_dialog.close).props(
                                        "flat no-caps"
                                    )
                                    ui.button(
                                        "Apagar ideias",
                                        icon="delete",
                                        on_click=confirm_purge_ideas,
                                    ).props("unelevated no-caps").classes(
                                        "bg-red-600 text-white rounded-xl"
                                    )

                            with ui.dialog() as projects_dialog, ui.card().classes(
                                "entity-card rounded-2xl p-6 min-w-96"
                            ):
                                ui.label("Apagar todos os projetos?").classes(
                                    "text-xl font-semibold"
                                )
                                ui.label(
                                    "Isso remove todos os projetos da lista principal. "
                                    "Ideias salvas na página de ideias não serão apagadas."
                                ).classes("text-sm text-[#858b86]")
                                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                                    ui.button("Cancelar", on_click=projects_dialog.close).props(
                                        "flat no-caps"
                                    )
                                    ui.button(
                                        "Apagar projetos",
                                        icon="delete_forever",
                                        on_click=confirm_purge_projects,
                                    ).props("unelevated no-caps").classes(
                                        "bg-red-600 text-white rounded-xl"
                                    )

                            with ui.dialog() as purge_dialog, ui.card().classes(
                                "entity-card rounded-2xl p-6 min-w-96"
                            ):
                                ui.label("Limpar banco da aplicacao?").classes(
                                    "text-xl font-semibold"
                                )
                                ui.label(
                                    "Isso apaga definitivamente projetos, roteiros, cenas, "
                                    "storyboards, assets, execucoes de prompt e ideias do "
                                    "laboratorio. Usuarios e configuracoes globais serao mantidos."
                                ).classes("text-sm text-[#858b86]")
                                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                                    ui.button("Cancelar", on_click=purge_dialog.close).props(
                                        "flat no-caps"
                                    )
                                    ui.button(
                                        "Limpar definitivamente",
                                        icon="delete_forever",
                                        on_click=_purge_application_data_from_ui,
                                    ).props("unelevated no-caps").classes(
                                        "bg-red-700 text-white rounded-xl"
                                    )

                            with ui.column().classes("w-full gap-3"):
                                with ui.element("div").classes(
                                    "border border-red-950 rounded-2xl p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3"
                                ):
                                    with ui.column().classes("gap-1"):
                                        ui.label("Ideias").classes("font-semibold")
                                        ui.label(
                                            f"{saved_idea_count} salva(s) e "
                                            f"{generated_idea_count} gerada(s)."
                                        ).classes("text-sm text-[#858b86]")
                                    ui.button(
                                        "Apagar todas as ideias",
                                        icon="delete_sweep",
                                        on_click=ideas_dialog.open,
                                    ).props("outline no-caps").classes(
                                        "text-red-300 border-red-900 rounded-xl"
                                    )

                                with ui.element("div").classes(
                                    "border border-red-950 rounded-2xl p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3"
                                ):
                                    with ui.column().classes("gap-1"):
                                        ui.label("Projetos").classes("font-semibold")
                                        ui.label(
                                            f"{project_count} projeto(s) ativo(s) no estúdio."
                                        ).classes("text-sm text-[#858b86]")
                                    ui.button(
                                        "Apagar todos os projetos",
                                        icon="delete_forever",
                                        on_click=projects_dialog.open,
                                    ).props("outline no-caps").classes(
                                        "text-red-300 border-red-900 rounded-xl"
                                    )

                                with ui.element("div").classes("hidden"):
                                    with ui.column().classes("gap-1"):
                                        ui.label("Projetos e ideias").classes("font-semibold")
                                        ui.label(
                                            f"Remove fisicamente {project_count} projeto(s), "
                                            f"{saved_idea_count} ideia(s) salva(s) e "
                                            f"{generated_idea_count} ideia(s) gerada(s)."
                                        ).classes("text-sm text-[#858b86]")
                                    ui.button(
                                        "Apagar definitivamente",
                                        icon="delete_forever",
                                        on_click=purge_dialog.open,
                                    ).props("outline no-caps").classes(
                                        "text-red-300 border-red-900 rounded-xl"
                                    )

    @ui.page("/projects/{project_id}", response_timeout=15)
    async def project_workspace(project_id: str) -> None:
        ui.navigate.to(f"/projects/{project_id}/script")
        return

    @ui.page("/projects/{project_id}/{section}", response_timeout=15)
    async def project_studio(project_id: str, section: str) -> None:
        _body_style()
        if section not in {"script", "assets", "storyboard", "video"}:
            ui.navigate.to(f"/projects/{project_id}/script")
            return
        try:
            project_uuid = UUID(project_id)
            summary = await _project_summary(project_uuid)
        except (ValueError, TypeError):
            summary = None
        if summary is None:
            with ui.column().classes("w-full min-h-screen items-center justify-center gap-4"):
                ui.icon("movie_off").classes("text-6xl acid")
                ui.label("Projeto não encontrado").classes("brand-type text-3xl font-bold")
                ui.button("Voltar ao início", on_click=lambda: ui.navigate.to("/")).classes(
                    "acid-bg"
                )
            return
        project: Project = summary["project"]
        counts: dict[str, int] = summary["counts"]
        allowed, reason = _workspace_section_access(section, counts)
        if not allowed:
            fallback = _first_available_workspace_section(counts)
            ui.notify(reason, color="warning")
            ui.navigate.to(f"/projects/{project_id}/{fallback}")
            return
        _workspace_header(project, section, counts)
        with ui.element("div").classes("workspace-layout flex w-full items-start flex-nowrap gap-0"):
            with ui.column().classes(
                "workspace-main flex-1 min-w-0 p-8 lg:p-10 gap-4 h-[calc(100vh-64px)] overflow-y-auto"
            ):
                if section == "script":
                    _render_script_area(project_uuid, summary)
                elif section == "assets":
                    _render_assets_area(project_uuid, summary)
                elif section == "storyboard":
                    _render_storyboard_area(project_uuid, summary)
                else:
                    _render_video_area(project_uuid, summary)
            _assistant_panel(project_uuid, section, summary)





