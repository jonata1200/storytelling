# ruff: noqa: E501

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
from app.storytelling.reference_upload import (
    ReferenceUploadError,
    prepare_reference_upload,
)
from app.storytelling.script_upload import ScriptUploadError, extract_script_text
from app.storytelling.service import coerce_duration_minutes
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
from app.ui.shared.generation_progress import generation_progress_dialog
from app.ui.shared.page_config import (
    DEFAULT_STORY_DURATION_MINUTES,
    IDEA_COUNT_OPTIONS,
    IDEA_GENRES,
    STORY_DURATION_OPTIONS,
    UI_GENERATION_TIMEOUT_SECONDS,
    friendly_ai_error,
    play_completion_sound,
    safe_close_ui_element,
    show_ai_error_popup,
)

BodyStyle = Callable[[], None]
ProjectCardsLoader = Callable[[], Awaitable[list[Any]]]
ProjectCardRenderer = Callable[[Any, str], None]
ChatProjectCreator = Callable[[str, list[dict[str, Any]] | None], Awaitable[None]]
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
    if completed <= 0 and elapsed_seconds >= 12:
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
    user_avatar: Callable[..., Any],
) -> None:
    @ui.page("/dashboard", response_timeout=15)
    async def dashboard() -> None:
        body_style()
        projects = await project_cards()
        home_sidebar("create")
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full px-5 md:px-10 lg:px-14 py-6 gap-9"):
                with ui.row().classes(
                    "w-full max-w-6xl mx-auto items-center justify-between min-h-14"
                ):
                    studio_logo()
                    with ui.row().classes("items-center gap-3"):
                        theme_toggle()
                        user_avatar(size="48px")
                with ui.column().classes("w-full max-w-4xl mx-auto items-center text-center gap-4"):
                    reference_uploads: list[dict[str, Any]] = []
                    uploaded_script: dict[str, Any] | None = None
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
                                    ui.label(
                                        "Digite uma ideia, cole um roteiro ou envie um arquivo."
                                    ).classes("text-xs text-[#8f9590]")
                            ui.button(icon="help_outline").props("flat round dense").classes(
                                "text-[#8f9590]"
                            ).tooltip(
                                "Um prompt simples ja basta: o agente cria briefing, ideia e roteiro inicial."
                            )

                        async def upload_script(event: Any) -> None:
                            nonlocal uploaded_script
                            try:
                                content = await event.file.read()
                                extracted = extract_script_text(event.file.name, content)
                            except ScriptUploadError as exc:
                                ui.notify(str(exc), color="warning")
                                return
                            except Exception as exc:
                                ui.notify(
                                    f"Não foi possível ler o arquivo: {exc}", color="negative"
                                )
                                return
                            previous_text = str(idea.value or "")
                            uploaded_script = {
                                "filename": event.file.name,
                                "content": extracted,
                                "previous_text": previous_text,
                            }
                            idea.value = extracted
                            idea.update()
                            attachment_list.refresh()
                            ui.notify(
                                f"Roteiro importado de {event.file.name}.",
                                color="positive",
                            )

                        @ui.refreshable
                        def attachment_list() -> None:
                            if uploaded_script is None and not reference_uploads:
                                return
                            with ui.row().classes("w-full gap-2 flex-wrap"):
                                if uploaded_script is not None:
                                    with ui.element("div").classes("prompt-attachment-chip"):
                                        ui.icon("description").classes("text-base")
                                        ui.label(f"Roteiro: {uploaded_script['filename']}").classes(
                                            "prompt-attachment-label"
                                        )
                                        ui.button(
                                            icon="close",
                                            on_click=remove_uploaded_script,
                                        ).props("flat round dense").classes(
                                            "prompt-attachment-remove"
                                        )
                                for index, item in enumerate(reference_uploads):
                                    with ui.element("div").classes("prompt-attachment-chip"):
                                        ui.icon("image").classes("text-base")
                                        ui.label(f"Imagem: {item['filename']}").classes(
                                            "prompt-attachment-label"
                                        )
                                        ui.button(
                                            icon="close",
                                            on_click=lambda item_index=index: (
                                                remove_reference_upload(item_index)
                                            ),
                                        ).props("flat round dense").classes(
                                            "prompt-attachment-remove"
                                        )

                        async def upload_reference_image(event: Any) -> None:
                            try:
                                content = await event.file.read()
                                prepared = prepare_reference_upload(
                                    event.file.name,
                                    content,
                                )
                            except ReferenceUploadError as exc:
                                ui.notify(str(exc), color="warning")
                                return
                            except Exception as exc:
                                ui.notify(
                                    f"Não foi possível anexar a imagem: {exc}", color="negative"
                                )
                                return
                            reference_uploads.append(prepared)
                            attachment_list.refresh()
                            ui.notify(
                                "Referência visual anexada.",
                                color="positive",
                            )

                        def remove_uploaded_script() -> None:
                            nonlocal uploaded_script
                            if uploaded_script is None:
                                return
                            if str(idea.value or "") == str(uploaded_script.get("content") or ""):
                                idea.value = str(uploaded_script.get("previous_text") or "")
                                idea.update()
                            uploaded_script = None
                            attachment_list.refresh()
                            ui.notify("Roteiro removido.", color="warning")

                        def remove_reference_upload(index: int) -> None:
                            if 0 <= index < len(reference_uploads):
                                reference_uploads.pop(index)
                                attachment_list.refresh()
                                ui.notify("Imagem de referência removida.", color="warning")

                        with ui.element("div").classes("prompt-composer w-full relative"):

                            async def submit_prompt_from_keyboard() -> None:
                                await create_project_from_chat_prompt(
                                    str(idea.value or ""),
                                    list(reference_uploads),
                                )

                            idea = (
                                ui.textarea(
                                    placeholder="Descreva sua história, cole um roteiro ou peça uma ideia..."
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
                            with ui.element("div").classes("hidden"):
                                ui.upload(
                                    label="Enviar roteiro",
                                    on_upload=upload_script,
                                    on_rejected=lambda: ui.notify(
                                        "Envie PDF ou DOCX com ate 10 MB.", color="warning"
                                    ),
                                    auto_upload=True,
                                    max_file_size=10_000_000,
                                ).props("id=prompt-script-upload accept=.pdf,.docx")
                                ui.upload(
                                    label="Enviar imagens",
                                    on_upload=upload_reference_image,
                                    on_rejected=lambda: ui.notify(
                                        "Envie JPG, PNG ou WebP com ate 10 MB.", color="warning"
                                    ),
                                    auto_upload=True,
                                    max_file_size=10_000_000,
                                ).props("id=prompt-reference-upload accept=.jpg,.jpeg,.png,.webp")
                            with ui.row().classes(
                                "prompt-composer-toolbar absolute items-center justify-between gap-2"
                            ):
                                with ui.row().classes("items-center gap-2 min-w-0"):
                                    ui.button(
                                        "Roteiro",
                                        icon="description",
                                        on_click=lambda: ui.run_javascript(
                                            "document.querySelector('#prompt-script-upload input[type=file]').click()"
                                        ),
                                    ).props("flat no-caps dense").classes("prompt-tool-button")
                                    ui.button(
                                        "Imagens",
                                        icon="image",
                                        on_click=lambda: ui.run_javascript(
                                            "document.querySelector('#prompt-reference-upload input[type=file]').click()"
                                        ),
                                    ).props("flat no-caps dense").classes("prompt-tool-button")
                                ui.button(
                                    icon="arrow_upward",
                                    on_click=lambda: create_project_from_chat_prompt(
                                        str(idea.value or ""),
                                        list(reference_uploads),
                                    ),
                                ).props("round unelevated").classes(
                                    "prompt-send-button acid-bg shadow-lg"
                                )
                        with ui.column().classes("w-full gap-2 text-left px-1"):
                            attachment_list()
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

                        def clear_dashboard_project_filters() -> None:
                            dashboard_project_search.value = ""
                            dashboard_project_status.value = "all"
                            dashboard_project_stage.value = "all"
                            dashboard_project_updated.value = "any"
                            dashboard_project_sort.value = "updated_desc"
                            for control in (
                                dashboard_project_search,
                                dashboard_project_status,
                                dashboard_project_stage,
                                dashboard_project_updated,
                                dashboard_project_sort,
                            ):
                                control.update()
                            dashboard_project_results.refresh()

                        with ui.row().classes("w-full gap-2 items-end flex-wrap"):
                            dashboard_project_search = (
                                ui.input(
                                    placeholder="Buscar projetos...",
                                    on_change=lambda _event=None: (
                                        dashboard_project_results.refresh()
                                    ),
                                )
                                .props(
                                    "outlined dense clearable debounce=250 prepend-icon=search aria-label='Buscar projetos recentes'"
                                )
                                .classes("flex-1 min-w-64")
                            )
                            dashboard_project_status = (
                                ui.select(
                                    PROJECT_STATUS_FILTER_OPTIONS,
                                    label="Status",
                                    value="all",
                                    on_change=lambda _event=None: (
                                        dashboard_project_results.refresh()
                                    ),
                                )
                                .props("outlined dense")
                                .classes("w-40")
                            )
                            dashboard_project_stage = (
                                ui.select(
                                    PROJECT_STAGE_FILTER_OPTIONS,
                                    label="Etapa",
                                    value="all",
                                    on_change=lambda _event=None: (
                                        dashboard_project_results.refresh()
                                    ),
                                )
                                .props("outlined dense")
                                .classes("w-40")
                            )
                            dashboard_project_updated = (
                                ui.select(
                                    PROJECT_UPDATED_FILTER_OPTIONS,
                                    label="Atualizacao",
                                    value="any",
                                    on_change=lambda _event=None: (
                                        dashboard_project_results.refresh()
                                    ),
                                )
                                .props("outlined dense")
                                .classes("w-44")
                            )
                            dashboard_project_sort = (
                                ui.select(
                                    PROJECT_SORT_OPTIONS,
                                    label="Ordenar",
                                    value="updated_desc",
                                    on_change=lambda _event=None: (
                                        dashboard_project_results.refresh()
                                    ),
                                )
                                .props("outlined dense")
                                .classes("w-48")
                            )
                            ui.button(
                                icon="filter_alt_off",
                                on_click=clear_dashboard_project_filters,
                            ).props("flat round dense").classes("text-[#aeb3ae]").tooltip(
                                "Limpar filtros"
                            )

                        @ui.refreshable
                        def dashboard_project_results() -> None:
                            filtered_projects = filter_projects(
                                projects,
                                query=dashboard_project_search.value,
                                status_filter=str(dashboard_project_status.value or "all"),
                                stage_filter=str(dashboard_project_stage.value or "all"),
                                updated_period=str(dashboard_project_updated.value or "any"),
                                sort=str(dashboard_project_sort.value or "updated_desc"),
                            )
                            ui.label(
                                f"{len(filtered_projects)} de {len(projects)} projeto(s)"
                            ).classes("text-xs text-[#7f8580]")
                            active_labels = project_active_filter_labels(
                                dashboard_project_search.value,
                                str(dashboard_project_status.value or "all"),
                                str(dashboard_project_stage.value or "all"),
                                str(dashboard_project_updated.value or "any"),
                                str(dashboard_project_sort.value or "updated_desc"),
                            )
                            if active_labels:
                                with ui.row().classes("w-full gap-2 flex-wrap"):
                                    for label in active_labels:
                                        ui.badge(label).classes(
                                            "bg-[#263225] text-[#d7f5c4] border border-[#4f6a45]"
                                        )
                            if not filtered_projects:
                                with ui.element("div").classes(
                                    "w-full border border-dashed border-[#363b36] rounded-2xl min-h-40 flex flex-col items-center justify-center text-[#969c97]"
                                ):
                                    ui.icon("search_off").classes("text-3xl")
                                    ui.label(
                                        "Nenhum projeto encontrado para esses filtros."
                                    ).classes("mt-2 text-sm font-semibold")
                                    if has_project_filters(
                                        dashboard_project_search.value,
                                        str(dashboard_project_status.value or "all"),
                                        str(dashboard_project_stage.value or "all"),
                                        str(dashboard_project_updated.value or "any"),
                                        str(dashboard_project_sort.value or "updated_desc"),
                                    ):
                                        ui.button(
                                            "Limpar filtros",
                                            icon="filter_alt_off",
                                            on_click=clear_dashboard_project_filters,
                                        ).props("flat no-caps").classes("acid mt-1")
                            with ui.grid().classes(
                                "w-full grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
                            ):
                                for project in filtered_projects:
                                    render_project_card(project, "/dashboard")
                                with (
                                    ui.element("div")
                                    .classes(
                                        "border border-dashed border-[#363b36] rounded-2xl min-h-52 flex flex-col items-center justify-center cursor-pointer text-[#969c97]"
                                    )
                                    .on("click", lambda: ui.navigate.to("/dashboard"))
                                ):
                                    ui.icon("add_circle_outline").classes("text-4xl acid")
                                    ui.label("Criar novo projeto").classes("mt-2 font-semibold")

                        dashboard_project_results()

    @ui.page("/projects", response_timeout=15)
    async def projects_page() -> None:
        body_style()
        projects = await project_cards()
        home_sidebar("projects")
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full max-w-6xl mx-auto px-6 py-8 gap-7"):
                with ui.column().classes("w-full gap-3"):
                    with ui.row().classes("w-full items-start justify-between gap-3 flex-nowrap"):
                        with ui.column().classes("gap-1 min-w-0 flex-1"):
                            ui.label("Projetos").classes(
                                "brand-type text-2xl md:text-4xl font-bold"
                            )
                            ui.label("Acompanhe e continue suas produções de vídeo.").classes(
                                "text-xs md:text-base text-[#8f9590]"
                            )
                        with ui.element("div").classes("shrink-0 ml-auto"):
                            theme_toggle()
                    with ui.row().classes("w-full justify-center md:justify-start"):
                        ui.button(
                            "Novo projeto",
                            icon="add",
                            on_click=lambda: ui.navigate.to("/dashboard"),
                        ).props("unelevated no-caps").classes(
                            "acid-bg rounded-xl text-base md:text-sm px-9 md:px-4 py-3 md:py-0 min-w-64 md:min-w-0"
                        )
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

                    def clear_project_filters() -> None:
                        project_search.value = ""
                        project_status.value = "all"
                        project_stage_select.value = "all"
                        project_updated.value = "any"
                        project_sort.value = "updated_desc"
                        for control in (
                            project_search,
                            project_status,
                            project_stage_select,
                            project_updated,
                            project_sort,
                        ):
                            control.update()
                        project_results.refresh()

                    with ui.row().classes("w-full gap-2 items-end flex-wrap"):
                        project_search = (
                            ui.input(
                                placeholder="Buscar projetos...",
                                on_change=lambda _event=None: project_results.refresh(),
                            )
                            .props(
                                "outlined dense clearable debounce=250 prepend-icon=search aria-label='Buscar projetos'"
                            )
                            .classes("flex-1 min-w-64")
                        )
                        project_status = (
                            ui.select(
                                PROJECT_STATUS_FILTER_OPTIONS,
                                label="Status",
                                value="all",
                                on_change=lambda _event=None: project_results.refresh(),
                            )
                            .props("outlined dense")
                            .classes("w-40")
                        )
                        project_stage_select = (
                            ui.select(
                                PROJECT_STAGE_FILTER_OPTIONS,
                                label="Etapa",
                                value="all",
                                on_change=lambda _event=None: project_results.refresh(),
                            )
                            .props("outlined dense")
                            .classes("w-40")
                        )
                        project_updated = (
                            ui.select(
                                PROJECT_UPDATED_FILTER_OPTIONS,
                                label="Atualizacao",
                                value="any",
                                on_change=lambda _event=None: project_results.refresh(),
                            )
                            .props("outlined dense")
                            .classes("w-44")
                        )
                        project_sort = (
                            ui.select(
                                PROJECT_SORT_OPTIONS,
                                label="Ordenar",
                                value="updated_desc",
                                on_change=lambda _event=None: project_results.refresh(),
                            )
                            .props("outlined dense")
                            .classes("w-48")
                        )
                        ui.button(
                            icon="filter_alt_off",
                            on_click=clear_project_filters,
                        ).props("flat round dense").classes("text-[#aeb3ae]").tooltip(
                            "Limpar filtros"
                        )

                    @ui.refreshable
                    def project_results() -> None:
                        filtered_projects = filter_projects(
                            projects,
                            query=project_search.value,
                            status_filter=str(project_status.value or "all"),
                            stage_filter=str(project_stage_select.value or "all"),
                            updated_period=str(project_updated.value or "any"),
                            sort=str(project_sort.value or "updated_desc"),
                        )
                        ui.label(f"{len(filtered_projects)} de {len(projects)} projeto(s)").classes(
                            "text-xs text-[#7f8580]"
                        )
                        active_labels = project_active_filter_labels(
                            project_search.value,
                            str(project_status.value or "all"),
                            str(project_stage_select.value or "all"),
                            str(project_updated.value or "any"),
                            str(project_sort.value or "updated_desc"),
                        )
                        if active_labels:
                            with ui.row().classes("w-full gap-2 flex-wrap"):
                                for label in active_labels:
                                    ui.badge(label).classes(
                                        "bg-[#263225] text-[#d7f5c4] border border-[#4f6a45]"
                                    )
                        if not filtered_projects:
                            with ui.element("div").classes(
                                "w-full border border-dashed border-[#363b36] rounded-2xl min-h-48 flex flex-col items-center justify-center text-[#969c97]"
                            ):
                                ui.icon("search_off").classes("text-4xl")
                                ui.label("Nenhum projeto encontrado para esses filtros.").classes(
                                    "mt-3 text-lg font-semibold"
                                )
                                if has_project_filters(
                                    project_search.value,
                                    str(project_status.value or "all"),
                                    str(project_stage_select.value or "all"),
                                    str(project_updated.value or "any"),
                                    str(project_sort.value or "updated_desc"),
                                ):
                                    ui.button(
                                        "Limpar filtros",
                                        icon="filter_alt_off",
                                        on_click=clear_project_filters,
                                    ).props("flat no-caps").classes("acid mt-2")
                        with ui.grid().classes(
                            "w-full grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
                        ):
                            for project in filtered_projects:
                                render_project_card(project, "/projects")
                            with (
                                ui.element("div")
                                .classes(
                                    "border border-dashed border-[#363b36] rounded-2xl min-h-52 flex flex-col items-center justify-center cursor-pointer text-[#969c97]"
                                )
                                .on("click", lambda: ui.navigate.to("/dashboard"))
                            ):
                                ui.icon("add_circle_outline").classes("text-4xl acid")
                                ui.label("Criar novo projeto").classes("mt-2 font-semibold")

                    project_results()

    @ui.page("/", response_timeout=15)
    @ui.page("/ideas", response_timeout=15)
    async def ideas_page() -> None:
        body_style()
        home_sidebar("ideas")
        saved_ideas = load_saved_ideas()
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full max-w-6xl mx-auto px-6 py-8 gap-7"):
                with ui.row().classes("w-full items-start justify-between gap-3 flex-nowrap"):
                    with ui.column().classes("gap-1 min-w-0 flex-1"):
                        with ui.row().classes("items-center gap-2 md:gap-3 flex-nowrap"):
                            ui.icon("lightbulb").classes("text-3xl md:text-4xl acid shrink-0")
                            ui.label("Laboratório de Ideias").classes(
                                "brand-type text-xl md:text-4xl font-bold leading-tight"
                            )
                        ui.label(
                            "Explore histórias livremente, sem criar um projeto de vídeo."
                        ).classes("text-xs md:text-base text-[#8f9590]")
                    with ui.element("div").classes("shrink-0 ml-auto"):
                        theme_toggle()

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

                    idea_generation_dialog, update_idea_generation_progress = (
                        generation_progress_dialog(
                            "Gerando ideias",
                            10,
                            "ideia",
                            _idea_generation_progress_detail(0, 10),
                        )
                    )

                    async def generate() -> None:
                        expected_count = int(idea_count_select.value or 10)
                        progress_state: dict[str, Any] = {
                            "completed": 0,
                            "latest_title": "",
                            "started_at": time.monotonic(),
                        }
                        progress_pulse = asyncio.create_task(
                            _pulse_idea_generation_progress(
                                update_idea_generation_progress,
                                progress_state,
                                expected_count,
                            )
                        )
                        idea_generation_dialog.open()
                        update_idea_generation_progress(
                            0,
                            expected_count,
                            _idea_generation_progress_detail(0, expected_count),
                        )
                        try:
                            replace_generated_ideas([])
                            generated: list[dict[str, Any]] = []
                            async with asyncio.timeout(UI_GENERATION_TIMEOUT_SECONDS):
                                async for batch in generate_freeform_idea_batches(
                                    "",
                                    count=expected_count,
                                    genre=str(genre_select.value or ""),
                                    target_duration_minutes=coerce_duration_minutes(
                                        duration_select.value
                                    ),
                                    batch_size=1,
                                ):
                                    batch_start = len(generated)
                                    for batch_index, generated_idea in enumerate(batch, 1):
                                        saved = save_idea(generated_idea)
                                        generated.append(saved)
                                        saved_ideas[:] = [
                                            existing
                                            for existing in saved_ideas
                                            if existing.get("id") != saved["id"]
                                        ]
                                        saved_ideas.insert(0, saved)
                                        completed = batch_start + batch_index
                                        progress_state["completed"] = completed
                                        progress_state["latest_title"] = clean_idea_title(
                                            saved.get("title"), "Ideia"
                                        )
                                        update_idea_generation_progress(
                                            completed,
                                            expected_count,
                                            _idea_generation_progress_detail(
                                                completed,
                                                expected_count,
                                                elapsed_seconds=int(
                                                    time.monotonic()
                                                    - float(progress_state["started_at"])
                                                ),
                                                latest_title=str(
                                                    progress_state["latest_title"]
                                                ),
                                            ),
                                        )
                                    refresh_idea_filter_options()
                                    saved_results.refresh()
                                    if len(generated) < expected_count:
                                        update_idea_generation_progress(
                                            len(generated),
                                            expected_count,
                                            (
                                                f"{len(generated)} ideia(s) salva(s). "
                                                f"Gerando próximo lote de "
                                                f"{expected_count - len(generated)}."
                                            ),
                                        )
                            if not generated:
                                raise RuntimeError("A IA não retornou ideias válidas.")
                            if len(generated) < expected_count:
                                update_idea_generation_progress(
                                    len(generated),
                                    expected_count,
                                    (
                                        f"A IA retornou {len(generated)} ideia(s) válida(s). "
                                        f"Faltaram {expected_count - len(generated)}."
                                    ),
                                )
                            refresh_idea_filter_options()
                            saved_results.refresh()
                            ui.notify(
                                f"{len(generated)} ideia(s) gerada(s) e salva(s).",
                                color="positive",
                            )
                            play_completion_sound()
                        except TimeoutError:
                            show_ai_error_popup(
                                "A geração demorou demais. Tente novamente ou escolha outro modelo.",
                                title="A IA demorou demais",
                            )
                        except Exception as exc:
                            show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
                        finally:
                            progress_pulse.cancel()
                            with suppress(asyncio.CancelledError):
                                await progress_pulse
                            safe_close_ui_element(idea_generation_dialog)

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
                    deleted = await delete_lab_idea_from_ui(idea_id, "saved")
                    if not deleted:
                        return
                    saved_ideas[:] = [
                        idea for idea in saved_ideas if str(idea.get("id")) != idea_id
                    ]
                    refresh_idea_filter_options()
                    saved_results.refresh()
                    ui.notify("Ideia apagada definitivamente.", color="warning")

                common_emotions = {
                    "Esperança",
                    "Curiosidade",
                    "Tensão",
                    "Alegria",
                    "Melancolia",
                    "Surpresa",
                }
                idea_genre_filter_options = {
                    "all": "Todos",
                    **{
                        genre: genre
                        for genre in sorted(
                            {*IDEA_GENRES, *unique_idea_filter_options(saved_ideas, "genre")},
                            key=str.casefold,
                        )
                    },
                }
                idea_emotion_filter_options = {
                    "all": "Todas",
                    **{
                        emotion: emotion
                        for emotion in sorted(
                            {
                                *common_emotions,
                                *unique_idea_filter_options(saved_ideas, "primary_emotion"),
                            },
                            key=str.casefold,
                        )
                    },
                }
                duration_values = {
                    float(coerce_duration_minutes(value)) for value in STORY_DURATION_OPTIONS
                }
                idea_duration_filter_options = {
                    "all": "Todas",
                    **{f"{value:g}": f"{value:g} min" for value in sorted(duration_values)},
                }

                def current_idea_genre_filter_options() -> dict[str, str]:
                    return {
                        "all": "Todos",
                        **{
                            genre: genre
                            for genre in sorted(
                                {
                                    *IDEA_GENRES,
                                    *unique_idea_filter_options(saved_ideas, "genre"),
                                },
                                key=str.casefold,
                            )
                        },
                    }

                def current_idea_emotion_filter_options() -> dict[str, str]:
                    return {
                        "all": "Todas",
                        **{
                            emotion: emotion
                            for emotion in sorted(
                                {
                                    *common_emotions,
                                    *unique_idea_filter_options(saved_ideas, "primary_emotion"),
                                },
                                key=str.casefold,
                            )
                        },
                    }

                def current_idea_duration_filter_options() -> dict[str, str]:
                    values = {
                        float(coerce_duration_minutes(value)) for value in STORY_DURATION_OPTIONS
                    }
                    return {
                        "all": "Todas",
                        **{f"{value:g}": f"{value:g} min" for value in sorted(values)},
                    }

                def refresh_idea_filter_options() -> None:
                    control_options = (
                        (idea_genre_filter, current_idea_genre_filter_options()),
                        (idea_emotion_filter, current_idea_emotion_filter_options()),
                        (idea_duration_filter, current_idea_duration_filter_options()),
                    )
                    for control, options in control_options:
                        control.options = options
                        if control.value not in options:
                            control.value = "all"
                        control.update()

                def clear_idea_filters() -> None:
                    idea_search.value = ""
                    idea_genre_filter.value = "all"
                    idea_emotion_filter.value = "all"
                    idea_duration_filter.value = "all"
                    idea_complexity_filter.value = "all"
                    idea_sort.value = "created_desc"
                    for control in (
                        idea_search,
                        idea_genre_filter,
                        idea_emotion_filter,
                        idea_duration_filter,
                        idea_complexity_filter,
                        idea_sort,
                    ):
                        control.update()
                    saved_results.refresh()

                with ui.column().classes("w-full gap-3"):
                    with ui.row().classes("w-full items-center justify-between gap-3"):
                        ui.label("Ideias salvas").classes("brand-type text-2xl font-bold")
                        ui.button(
                            icon="filter_alt_off",
                            on_click=clear_idea_filters,
                        ).props("flat round dense").classes("text-[#aeb3ae]").tooltip(
                            "Limpar filtros"
                        )
                    with ui.row().classes("w-full gap-2 items-end flex-wrap"):
                        idea_search = (
                            ui.input(
                                placeholder="Buscar ideias...",
                                on_change=lambda _event=None: saved_results.refresh(),
                            )
                            .props(
                                "outlined dense clearable debounce=250 prepend-icon=search aria-label='Buscar ideias'"
                            )
                            .classes("flex-1 min-w-64")
                        )
                        idea_genre_filter = (
                            ui.select(
                                idea_genre_filter_options,
                                label="Gênero",
                                value="all",
                                on_change=lambda _event=None: saved_results.refresh(),
                            )
                            .props("outlined dense")
                            .classes("w-44")
                        )
                        idea_emotion_filter = (
                            ui.select(
                                idea_emotion_filter_options,
                                label="Emoção",
                                value="all",
                                on_change=lambda _event=None: saved_results.refresh(),
                            )
                            .props("outlined dense")
                            .classes("w-44")
                        )
                        idea_duration_filter = (
                            ui.select(
                                idea_duration_filter_options,
                                label="Duração",
                                value="all",
                                on_change=lambda _event=None: saved_results.refresh(),
                            )
                            .props("outlined dense")
                            .classes("w-36")
                        )
                        idea_complexity_filter = (
                            ui.select(
                                IDEA_COMPLEXITY_FILTER_OPTIONS,
                                label="Complexidade",
                                value="all",
                                on_change=lambda _event=None: saved_results.refresh(),
                            )
                            .props("outlined dense")
                            .classes("w-44")
                        )
                        idea_sort = (
                            ui.select(
                                IDEA_SORT_OPTIONS,
                                label="Ordenar",
                                value="created_desc",
                                on_change=lambda _event=None: saved_results.refresh(),
                            )
                            .props("outlined dense")
                            .classes("w-52")
                        )

                @ui.refreshable
                def saved_results() -> None:
                    if not saved_ideas:
                        ui.label("Nenhuma ideia salva ainda.").classes("text-sm text-[#777d78]")
                        return
                    filtered_ideas = filter_ideas(
                        saved_ideas,
                        query=idea_search.value,
                        genre_filter=str(idea_genre_filter.value or "all"),
                        emotion_filter=str(idea_emotion_filter.value or "all"),
                        duration_filter=idea_duration_filter.value,
                        complexity_filter=str(idea_complexity_filter.value or "all"),
                        sort=str(idea_sort.value or "created_desc"),
                    )
                    ui.label(f"{len(filtered_ideas)} de {len(saved_ideas)} ideia(s)").classes(
                        "text-xs text-[#7f8580]"
                    )
                    active_labels = idea_active_filter_labels(
                        idea_search.value,
                        str(idea_genre_filter.value or "all"),
                        str(idea_emotion_filter.value or "all"),
                        idea_duration_filter.value,
                        str(idea_complexity_filter.value or "all"),
                        str(idea_sort.value or "created_desc"),
                    )
                    if active_labels:
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            for label in active_labels:
                                ui.badge(label).classes(
                                    "bg-[#263225] text-[#d7f5c4] border border-[#4f6a45]"
                                )
                    if not filtered_ideas:
                        with ui.element("div").classes(
                            "w-full border border-dashed border-[#363b36] rounded-2xl min-h-48 flex flex-col items-center justify-center text-[#969c97]"
                        ):
                            ui.icon("search_off").classes("text-4xl")
                            ui.label("Nenhuma ideia encontrada para esses filtros.").classes(
                                "mt-3 text-lg font-semibold"
                            )
                            if has_idea_filters(
                                idea_search.value,
                                str(idea_genre_filter.value or "all"),
                                str(idea_emotion_filter.value or "all"),
                                idea_duration_filter.value,
                                str(idea_complexity_filter.value or "all"),
                                str(idea_sort.value or "created_desc"),
                            ):
                                ui.button(
                                    "Limpar filtros",
                                    icon="filter_alt_off",
                                    on_click=clear_idea_filters,
                                ).props("flat no-caps").classes("acid mt-2")
                        return
                    with ui.grid().classes("w-full grid-cols-1 lg:grid-cols-3 gap-4"):
                        for idea in filtered_ideas:
                            with ui.element("article").classes(
                                "entity-card rounded-2xl p-5 flex flex-col min-h-80"
                            ):
                                ui.label(
                                    clean_idea_title(idea.get("title"), "História sem título")
                                ).classes("brand-type text-2xl font-bold")
                                with ui.row().classes("gap-2 mt-3 flex-wrap"):
                                    ui.label(str(idea.get("genre") or "Gênero sugerido")).classes(
                                        "idea-badge-genre rounded-md px-2 py-0.5 text-xs font-medium"
                                    )
                                    ui.label(
                                        str(idea.get("primary_emotion") or "Emoção sugerida")
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
                                        on_click=lambda idea_id=saved_idea_id: delete_saved(
                                            idea_id
                                        ),
                                    ).props("flat no-caps").classes("text-red-300")
                                    ui.button(
                                        "Desenvolver",
                                        icon="arrow_forward",
                                        on_click=lambda item=idea: create_project_from_idea(item),
                                    ).props("flat no-caps").classes("acid")

                saved_results()
