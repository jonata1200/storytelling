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
from app.ui.shared.page_config import STEP_LOADING_COPY, friendly_ai_error, show_ai_error_popup

logger = logging.getLogger(__name__)
LoadingDialogFactory = Callable[[str, str], Any]
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
        "finalization": "Peça ajustes de timeline, export ou arquivo final.",
        "dubbing": "Peça ajustes de idioma, voz ou sincronização.",
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
        "finalization": (
            "Sugestões que posso ajudar agora: montar a timeline final, exportar o "
            "arquivo único, revisar duração ou preparar a entrega."
        ),
        "dubbing": (
            "Sugestões que posso ajudar agora: gerar dublagem, revisar idioma alvo, "
            "atualizar o status do job ou preparar a etapa final após o áudio."
        ),
    }
    chat_loading_copy = {
        "generate_ideas": STEP_LOADING_COPY["ideas"],
        "generate_script": STEP_LOADING_COPY["script"],
        "revise_script": ("Revisando roteiro", "A IA está aplicando ajustes no roteiro."),
        "generate_assets": STEP_LOADING_COPY["visual"],
        "approve_visual_prompt": (
            "Gerando imagens",
            "A IA está criando imagens a partir dos prompts aprovados.",
        ),
        "generate_storyboard": STEP_LOADING_COPY["storyboard"],
        "generate_video": (
            "Gerando clipes",
            "A IA está criando clipes a partir dos prompts aprovados.",
        ),
        "generate_dubbing": STEP_LOADING_COPY["dubbing"],
        "generate_finalization": STEP_LOADING_COPY["finalization"],
        "run_quality": STEP_LOADING_COPY["quality"],
    }
    action_loading_dialogs = {
        action: loading_dialog_factory(title, message)
        for action, (title, message) in chat_loading_copy.items()
    }
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
            predicted_action = classify_project_chat_action(user_message, active)
            loading_dialog = action_loading_dialogs.get(predicted_action)
            if loading_dialog is not None:
                loading_dialog.open()
            error_popup: tuple[str, str | None, str] | None = None

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
                    if result.failed:
                        error_popup = (
                            result.message,
                            None,
                            "A IA não concluiu a solicitação",
                        )
            except Exception as exc:
                logger.exception(
                    "Não foi possível responder ao chat do projeto %s na etapa %s",
                    project_id,
                    active,
                )
                response = friendly_ai_error(exc)
                error_popup = (response, str(exc), "Falha na IA")
            if loading_dialog is not None:
                loading_dialog.close()
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
