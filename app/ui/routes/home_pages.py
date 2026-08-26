# ruff: noqa: E501, F401, I001

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from nicegui import ui

from app.storytelling.idea_lab import (
    generate_freeform_idea_batches,
    load_saved_ideas,
    replace_generated_ideas,
    save_idea,
)
from app.storytelling.service import coerce_duration_minutes
from app.ui.routes.home_ideas_page import render_ideas_page
from app.ui.routes.home_projects_page import render_projects_page
from app.ui.search_filters import (
    IDEA_COMPLEXITY_FILTER_OPTIONS,
    IDEA_SORT_OPTIONS,
    PROJECT_SORT_OPTIONS,
    PROJECT_STAGE_FILTER_OPTIONS,
    PROJECT_STATUS_FILTER_OPTIONS,
    PROJECT_UPDATED_FILTER_OPTIONS,
    filter_ideas,
    filter_projects,
    has_idea_filters,
    has_project_filters,
    idea_active_filter_labels,
    project_active_filter_labels,
    unique_idea_filter_options,
)
from app.ui.shared.generation_progress import (
    OPERATION_CANCELLED_MESSAGE,
    generation_progress_dialog,
    mark_dialog_task_cancelable,
)
from app.ui.shared.page_config import (
    IDEA_COUNT_OPTIONS,
    IDEA_EMOTION_OPTIONS,
    IDEA_GENRES,
    STORY_DURATION_OPTIONS,
    block_if_missing_api_keys_for_step,
    friendly_ai_error,
    play_completion_sound,
    safe_close_ui_element,
    safe_notify,
    show_ai_error_popup,
)

BodyStyle = Callable[[], None]
ProjectCardsLoader = Callable[[], Awaitable[list[Any]]]
ProjectCardRenderer = Callable[[Any, str], None]
ChatProjectCreator = Callable[[str], Awaitable[None]]
IdeaProjectCreator = Callable[[dict[str, Any]], Awaitable[None]]
IdeaDeleter = Callable[[str, str], Awaitable[bool]]
LoadingDialogFactory = Callable[[str, Any], Any]
TextCleaner = Callable[[Any, str], str]

DASHBOARD_PROMPT_KEYDOWN_JS = """
(event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    emit();
  }
}
"""


IDEA_GENERATION_PROGRESS_PULSE_SECONDS = 2.5
IDEA_LAB_UI_TIMEOUT_SECONDS = 300


def _idea_generation_progress_detail(
    completed: int,
    total: int,
    *,
    elapsed_seconds: int = 0,
    latest_title: str = "",
) -> str:
    remaining = max(total - completed, 0)
    created_text = f"{completed} ideia(s)" if completed > 0 else "nada ainda"
    missing_text = f"{remaining} ideia(s)" if remaining > 0 else "nada"
    if completed <= 0 and elapsed_seconds >= 60:
        now = (
            "Agora: a IA esta demorando mais que o normal. "
            "Se passar do limite, a aplicacao vai encerrar e mostrar o erro."
        )
    elif completed <= 0 and elapsed_seconds >= 12:
        now = "Agora: a IA ainda esta respondendo; a primeira ideia sera salva assim que chegar."
    elif completed <= 0:
        now = "Agora: aguardando a IA criar a primeira ideia."
    elif remaining > 0:
        title_fragment = f" Ultima: {latest_title}." if latest_title else ""
        now = f"Agora: salvando ideias e gerando as proximas.{title_fragment}"
    else:
        now = "Agora: finalizando e atualizando a lista."
    return "\n".join(
        [
            now,
            f"Criado: {created_text}.",
            f"Falta criar: {missing_text}.",
        ]
    )


async def _pulse_idea_generation_progress(
    update_progress: Callable[[int, int, str], None],
    state: dict[str, Any],
    total: int,
) -> None:
    while True:
        await asyncio.sleep(IDEA_GENERATION_PROGRESS_PULSE_SECONDS)
        started_at = float(state.get("started_at") or time.monotonic())
        update_progress(
            int(state.get("completed") or 0),
            total,
            _idea_generation_progress_detail(
                int(state.get("completed") or 0),
                total,
                elapsed_seconds=int(time.monotonic() - started_at),
                latest_title=str(state.get("latest_title") or ""),
            ),
        )


def register_home_pages(
    *,
    body_style: BodyStyle,
    project_cards: ProjectCardsLoader,
    render_project_card: ProjectCardRenderer,
    create_project_from_chat_prompt: ChatProjectCreator,
    create_project_from_idea: IdeaProjectCreator,
    delete_lab_idea_from_ui: IdeaDeleter,
    loading_dialog_factory: LoadingDialogFactory,
    clean_idea_title: TextCleaner,
    home_sidebar: Callable[[str], None],
    studio_logo: Callable[[], None],
    theme_toggle: Callable[[], Any],
) -> None:
    @ui.page("/dashboard", response_timeout=15)
    async def dashboard() -> None:
        body_style()
        home_sidebar("create")
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full px-5 md:px-10 lg:px-14 py-6 gap-9"):
                with ui.row().classes(
                    "w-full max-w-6xl mx-auto items-center justify-between min-h-14"
                ):
                    studio_logo()
                    with ui.row().classes("items-center gap-3"):
                        theme_toggle()
                with ui.column().classes("w-full max-w-4xl mx-auto items-center text-center gap-4"):
                    with ui.element("div").classes(
                        "chat-shell glass rounded-3xl p-4 md:p-5 w-full min-h-[260px] flex flex-col gap-3"
                    ):
                        with ui.row().classes("w-full items-center justify-between gap-3"):
                            with ui.row().classes("items-center gap-2 min-w-0"):
                                ui.icon("edit_note").classes("text-2xl acid shrink-0")
                                with ui.column().classes("gap-0 text-left min-w-0"):
                                    ui.label("Comece sua história").classes(
                                        "brand-type text-lg md:text-xl font-bold"
                                    )
                                    ui.label("Digite uma ideia ou peça uma história.").classes(
                                        "text-xs text-[#8f9590]"
                                    )
                            ui.button(icon="help_outline").props("flat round dense").classes(
                                "text-[#8f9590]"
                            ).tooltip(
                                "Um prompt simples ja basta: o agente cria briefing, ideia e roteiro inicial."
                            )

                        with ui.element("div").classes("prompt-composer w-full relative"):

                            async def submit_prompt_from_keyboard() -> None:
                                await create_project_from_chat_prompt(str(idea.value or ""))

                            idea = (
                                ui.textarea(
                                    placeholder="Descreva sua história ou peça uma ideia..."
                                )
                                .props("outlined autogrow input-style='min-height:160px'")
                                .classes(
                                    "prompt-composer-input w-full text-base md:text-lg flex-1 text-left"
                                )
                            )
                            idea.on(
                                "keydown",
                                submit_prompt_from_keyboard,
                                js_handler=DASHBOARD_PROMPT_KEYDOWN_JS,
                            )
                            with ui.row().classes(
                                "prompt-composer-toolbar absolute items-center justify-end gap-2"
                            ):
                                ui.button(
                                    icon="arrow_upward",
                                    on_click=lambda: create_project_from_chat_prompt(
                                        str(idea.value or "")
                                    ),
                                ).props("round unelevated").classes(
                                    "prompt-send-button acid-bg shadow-lg"
                                )
    @ui.page("/projects", response_timeout=15)
    async def projects_page() -> None:
        await render_projects_page(
            body_style=body_style,
            project_cards=project_cards,
            render_project_card=render_project_card,
            home_sidebar=home_sidebar,
            studio_logo=studio_logo,
            theme_toggle=theme_toggle,
        )

    @ui.page("/", response_timeout=15)
    @ui.page("/ideas", response_timeout=15)
    async def ideas_page() -> None:
        await render_ideas_page(
            body_style=body_style,
            create_project_from_idea=create_project_from_idea,
            delete_lab_idea_from_ui=delete_lab_idea_from_ui,
            loading_dialog_factory=loading_dialog_factory,
            clean_idea_title=clean_idea_title,
            home_sidebar=home_sidebar,
            studio_logo=studio_logo,
            theme_toggle=theme_toggle,
        )
