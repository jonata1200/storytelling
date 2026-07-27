# ruff: noqa: E501

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from nicegui import ui

from app.storytelling.idea_lab import (
    generate_freeform_ideas,
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
from app.ui.shared.page_config import (
    DEFAULT_STORY_DURATION_MINUTES,
    IDEA_COUNT_OPTIONS,
    IDEA_GENRES,
    STEP_LOADING_COPY,
    STORY_DURATION_OPTIONS,
    UI_GENERATION_TIMEOUT_SECONDS,
    friendly_ai_error,
    show_ai_error_popup,
)

BodyStyle = Callable[[], None]
ProjectCardsLoader = Callable[[], Awaitable[list[Any]]]
ProjectCardRenderer = Callable[[Any, str], None]
ChatProjectCreator = Callable[[str, list[dict[str, Any]] | None], Awaitable[None]]
IdeaProjectCreator = Callable[[dict[str, Any]], Awaitable[None]]
IdeaDeleter = Callable[[str, str], Awaitable[bool]]
LoadingDialogFactory = Callable[[str, str], Any]
TextCleaner = Callable[[Any, str], str]


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
                        idea = (
                            ui.textarea(
                                placeholder="Descreva sua história, cole um roteiro ou peça uma ideia..."
                            )
                            .props("outlined autogrow input-style='min-height:140px'")
                            .classes("w-full text-base md:text-lg flex-1 text-left")
                        )

                        async def upload_script(event: Any) -> None:
                            try:
                                content = await event.file.read()
                                extracted = extract_script_text(event.file.name, content)
                            except ScriptUploadError as exc:
                                ui.notify(str(exc), color="warning")
                                return
                            except Exception as exc:
                                ui.notify(f"Não foi possível ler o arquivo: {exc}", color="negative")
                                return
                            idea.value = extracted
                            idea.update()
                            ui.notify(
                                f"Roteiro importado de {event.file.name}.",
                                color="positive",
                            )

                        @ui.refreshable
                        def reference_upload_list() -> None:
                            if not reference_uploads:
                                ui.label("Nenhuma imagem de referência anexada.").classes(
                                    "text-xs text-[#8f9590]"
                                )
                                return
                            with ui.row().classes("w-full gap-2 flex-wrap"):
                                for item in reference_uploads:
                                    ui.badge(
                                        f"Referência visual: {item['filename']}"
                                    ).classes(
                                        "rounded-lg px-2 py-1 bg-[#243342] text-[#dcecff]"
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
                                ui.notify(f"Não foi possível anexar a imagem: {exc}", color="negative")
                                return
                            reference_uploads.append(prepared)
                            reference_upload_list.refresh()
                            ui.notify(
                                "Referência visual anexada.",
                                color="positive",
                            )

                        with ui.row().classes(
                            "w-full items-center justify-between gap-3 flex-wrap px-1 pb-1"
                        ):
                            with ui.row().classes("items-center gap-2 flex-wrap"):
                                ui.upload(
                                    label="Enviar roteiro",
                                    on_upload=upload_script,
                                    on_rejected=lambda: ui.notify(
                                        "Envie PDF ou DOCX com ate 10 MB.", color="warning"
                                    ),
                                    auto_upload=True,
                                    max_file_size=10_000_000,
                                ).props("accept=.pdf,.docx").classes(
                                    "script-upload-control text-left"
                                )
                                ui.upload(
                                    label="Enviar imagens",
                                    on_upload=upload_reference_image,
                                    on_rejected=lambda: ui.notify(
                                        "Envie JPG, PNG ou WebP com ate 10 MB.", color="warning"
                                    ),
                                    auto_upload=True,
                                    max_file_size=10_000_000,
                                ).props("accept=.jpg,.jpeg,.png,.webp").classes(
                                    "script-upload-control text-left"
                                )
                            ui.button(
                                icon="arrow_upward",
                                on_click=lambda: create_project_from_chat_prompt(
                                    str(idea.value or ""),
                                    list(reference_uploads),
                                ),
                            ).props("round unelevated size=lg").classes("acid-bg shadow-lg")
                        with ui.column().classes("w-full gap-2 text-left px-1"):
                            reference_upload_list()
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
                    with ui.grid().classes(
                        "w-full grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
                    ):
                        for project in projects:
                            render_project_card(project, "/projects")

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

                    loading_title, loading_message = STEP_LOADING_COPY["ideas"]
                    loading_dialog = loading_dialog_factory(
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
                            show_ai_error_popup(
                                "A geração demorou demais. Tente novamente ou escolha outro modelo.",
                                title="A IA demorou demais",
                            )
                        except Exception as exc:
                            show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
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
                    deleted = await delete_lab_idea_from_ui(idea_id, "saved")
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
                                    clean_idea_title(idea.get("title"), "História sem título")
                                ).classes(
                                    "brand-type text-2xl font-bold"
                                )
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
                                        on_click=lambda idea_id=saved_idea_id: delete_saved(idea_id),
                                    ).props("flat no-caps").classes("text-red-300")
                                    ui.button(
                                        "Desenvolver",
                                        icon="arrow_forward",
                                        on_click=lambda item=idea: create_project_from_idea(item),
                                    ).props("flat no-caps").classes("acid")

                saved_results()



