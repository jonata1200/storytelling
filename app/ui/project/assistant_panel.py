import asyncio
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from nicegui import ui

from app.database.session import AsyncSessionLocal
from app.generation.project_agent import classify_project_chat_action, handle_project_chat
from app.ui.shared.assistant_state import clear_assistant_draft as _clear_assistant_draft
from app.ui.shared.assistant_state import clear_assistant_messages as _clear_assistant_messages
from app.ui.shared.assistant_state import load_assistant_draft as _load_assistant_draft
from app.ui.shared.assistant_state import load_assistant_messages as _load_assistant_messages
from app.ui.shared.assistant_state import safe_client_navigation as _safe_client_navigation
from app.ui.shared.assistant_state import safe_refresh as _safe_refresh
from app.ui.shared.assistant_state import save_assistant_draft as _save_assistant_draft
from app.ui.shared.assistant_state import save_assistant_messages as _save_assistant_messages
from app.ui.shared.generation_progress import (
    OPERATION_CANCELLED_MESSAGE,
    generation_progress_dialog,
    mark_dialog_task_cancelable,
)
from app.ui.shared.page_config import (
    action_loading_copy,
    block_if_missing_api_keys_for_step,
    friendly_ai_error,
    play_completion_sound,
    safe_close_ui_element,
    show_ai_error_popup,
)

logger = logging.getLogger(__name__)
LoadingDialogFactory = Callable[[str, Any], Any]
ProjectAiActionReader = Callable[[dict[str, Any]], dict[str, Any]]
AiActionSummaryHandler = Callable[[UUID, dict[str, Any]], None]


def render_assistant_panel(
    project_id: UUID,
    active: str,
    summary: dict[str, Any],
    *,
    loading_dialog_factory: LoadingDialogFactory,
    project_ai_action: ProjectAiActionReader,
    sync_ai_action_events_to_chat: AiActionSummaryHandler,
    notify_ai_action_failure_once: AiActionSummaryHandler,
) -> None:
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
            "orientar movimento de câmera, ajustar ritmo ou propor variações."
        ),
    }
    counts = summary.get("counts")
    count_map = counts if isinstance(counts, dict) else {}
    chat_actions = (
        "generate_ideas",
        "generate_script",
        "revise_script",
        "generate_assets",
        "approve_visual_prompt",
        "approve_storyboard_prompt",
        "generate_storyboard",
        "generate_video",
    )
    chat_loading_copy = {
        action: action_loading_copy(action, count_map)
        for action in chat_actions
    }
    action_loading_dialogs: dict[str, Any] = {}
    action_loading_progress_updates: dict[str, Callable[[int, int, str], None]] = {}
    storyboard_progress_actions = {"approve_storyboard_prompt", "generate_storyboard"}
    storyboard_progress_total = max(
        int(count_map.get("shots") or 0) - int(count_map.get("frames") or 0),
        1,
    )
    action_loading_totals: dict[str, int] = {}
    for action, (title, message) in chat_loading_copy.items():
        if action == "revise_script":
            detail = message.as_text() if hasattr(message, "as_text") else str(message)
            dialog, update_progress = generation_progress_dialog(
                title,
                3,
                "etapa",
                detail,
            )
            action_loading_dialogs[action] = dialog
            action_loading_progress_updates[action] = update_progress
            action_loading_totals[action] = 3
        elif action in storyboard_progress_actions:
            detail = message.as_text() if hasattr(message, "as_text") else str(message)
            dialog, update_progress = generation_progress_dialog(
                title,
                storyboard_progress_total,
                "quadro",
                detail,
            )
            action_loading_dialogs[action] = dialog
            action_loading_progress_updates[action] = update_progress
            action_loading_totals[action] = storyboard_progress_total
        else:
            action_loading_dialogs[action] = loading_dialog_factory(title, message)
    sync_ai_action_events_to_chat(project_id, project_ai_action(summary))
    notify_ai_action_failure_once(project_id, summary)
    messages = _load_assistant_messages(project_id, active, assistant_suggestions)
    draft = _load_assistant_draft(project_id)

    def clear_conversation() -> None:
        _clear_assistant_messages(project_id)
        messages[:] = _load_assistant_messages(project_id, active, assistant_suggestions)
        _safe_refresh(conversation)
        ui.notify("Histórico da conversa limpo.", color="info")

    with ui.element("aside").classes(
        "right-assistant flex flex-col min-h-0 mt-0 gap-4 sticky top-0 self-start"
    ):
        with ui.element("div").classes(
            "flex w-full items-center justify-between mt-0 pt-0 shrink-0"
        ):
            with ui.element("div").classes("flex items-center gap-2"):
                ui.icon("auto_awesome").classes("acid")
                ui.label("Diretor IA").classes("font-semibold")
            with ui.row().classes("items-center gap-2"):
                ui.badge("online").classes("bg-[#26301f] text-white")
                with (
                    ui.button(icon="delete_sweep", on_click=clear_conversation)
                    .props("flat round dense")
                    .classes("text-[#7c8a7c]")
                ):
                    ui.tooltip("Limpar histórico da conversa")

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
                                "assistant-chat-bubble w-fit rounded-2xl px-4 py-3 "
                                "text-sm leading-5 "
                                + ("max-w-[88%] " if sent else "max-w-full ")
                                + (
                                    "acid-bg assistant-chat-user-bubble rounded-br-sm"
                                    if sent
                                    else "glass text-[#c8ccc8] rounded-bl-sm"
                                )
                            )

        with ui.column().classes("assistant-chat-messages w-full flex-1 min-h-0 overflow-y-auto"):
            conversation()

        async def send_message(text: str | None = None) -> None:
            client = prompt.client
            raw_message = text if isinstance(text, str) else draft.get("message") or prompt.value
            user_message = str(raw_message or "").strip()
            if not user_message:
                return
            predicted_action = classify_project_chat_action(user_message, active)
            if predicted_action == "chat":
                if block_if_missing_api_keys_for_step("director_agent_chat"):
                    return
            elif block_if_missing_api_keys_for_step(predicted_action):
                return
            messages.append({"role": "user", "content": user_message})
            pending_message = {
                "role": "assistant_pending",
                "content": "Diretor IA está buscando a melhor resposta...",
            }
            messages.append(pending_message)
            _save_assistant_messages(project_id, messages)
            _clear_assistant_draft(project_id)
            draft["message"] = ""
            prompt.value = ""
            _safe_refresh(conversation)
            should_reload = False
            loading_dialog = action_loading_dialogs.get(predicted_action)
            loading_progress_update = action_loading_progress_updates.get(predicted_action)
            loading_progress_total = action_loading_totals.get(predicted_action, 3)
            loading_progress_completed = 0
            if loading_dialog is not None:
                loading_dialog.open()
                mark_dialog_task_cancelable(loading_dialog)
            error_popup: tuple[str, str | None, str] | None = None

            async def report_progress(content: Any) -> None:
                nonlocal loading_progress_completed
                if isinstance(content, dict):
                    progress_message = str(
                        content.get("detail") or content.get("message") or ""
                    ).strip()
                    if not progress_message:
                        return
                    if loading_progress_update is not None:
                        try:
                            completed = int(content.get("completed") or 0)
                            total = int(content.get("total") or loading_progress_total)
                        except (TypeError, ValueError):
                            completed = loading_progress_completed
                            total = loading_progress_total
                        loading_progress_completed = completed
                        loading_progress_update(completed, max(total, 1), progress_message)
                    pending_message["content"] = progress_message
                    _save_assistant_messages(project_id, messages)
                    _safe_refresh(conversation)
                    await asyncio.sleep(0)
                    return

                progress_message = str(content or "").strip()
                if not progress_message:
                    return
                pending_message["content"] = progress_message
                if loading_progress_update is not None:
                    loading_progress_completed = min(
                        loading_progress_completed + 1,
                        max(loading_progress_total - 1, 1),
                    )
                    loading_progress_update(
                        loading_progress_completed,
                        loading_progress_total,
                        progress_message,
                    )
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
                    if result.failed:
                        error_popup = (
                            result.message,
                            None,
                            "A IA não concluiu a solicitação",
                        )
            except asyncio.CancelledError:
                response = OPERATION_CANCELLED_MESSAGE
                error_popup = None
                should_reload = True
            except Exception as exc:
                logger.exception(
                    "Não foi possível responder ao chat do projeto %s na etapa %s",
                    project_id,
                    active,
                )
                response = friendly_ai_error(exc)
                error_popup = (response, str(exc), "Falha na IA")
            if loading_progress_update is not None:
                loading_progress_update(loading_progress_total, loading_progress_total, response)
                await asyncio.sleep(0.1)
            if loading_dialog is not None:
                safe_close_ui_element(loading_dialog)
            if error_popup is not None:
                popup_message, popup_details, popup_title = error_popup
                show_ai_error_popup(
                    popup_message,
                    details=popup_details,
                    title=popup_title,
                )
            if pending_message in messages:
                messages.remove(pending_message)
            messages.append({"role": "assistant", "content": response})
            _save_assistant_messages(project_id, messages)
            if should_reload:
                if error_popup is None and predicted_action in {
                    "generate_ideas",
                    "generate_script",
                    "revise_script",
                    "generate_assets",
                    "approve_visual_prompt",
                    "approve_storyboard_prompt",
                    "generate_storyboard",
                }:
                    play_completion_sound()
                if loading_dialog is not None:
                    safe_close_ui_element(loading_dialog)
                    await asyncio.sleep(0.1)
                _safe_client_navigation(client)
                return
            _safe_refresh(conversation)

        with ui.row().classes("w-full items-end gap-2 shrink-0"):
            prompt = (
                ui.textarea(placeholder=prompts[active])
                .bind_value(draft, "message")
                .props("outlined dense autogrow rows=1")
                .classes("flex-1 assistant-chat-input")
            )
            prompt.on_value_change(
                lambda event: _save_assistant_draft(project_id, event.value)
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
                on_click=lambda: send_message(),
            ).props("round unelevated").classes("acid-bg shrink-0 mb-1")
