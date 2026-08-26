# ruff: noqa: E501, F841

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

BodyStyle = Callable[[], None]
IdeaProjectCreator = Callable[[dict[str, Any]], Awaitable[None]]
IdeaDeleter = Callable[[str, str], Awaitable[bool]]
LoadingDialogFactory = Callable[[str, Any], Any]
TextCleaner = Callable[[Any, str], str]


async def render_ideas_page(
    *,
    body_style: BodyStyle,
    create_project_from_idea: IdeaProjectCreator,
    delete_lab_idea_from_ui: IdeaDeleter,
    loading_dialog_factory: LoadingDialogFactory,
    clean_idea_title: TextCleaner,
    home_sidebar: Callable[[str], None],
    studio_logo: Callable[[], None],
    theme_toggle: Callable[[], Any],
) -> None:
    from app.ui.routes import home_pages as deps

    asyncio = deps.asyncio
    time = deps.time
    suppress = deps.suppress
    ui = deps.ui
    IDEA_COMPLEXITY_FILTER_OPTIONS = deps.IDEA_COMPLEXITY_FILTER_OPTIONS
    IDEA_COUNT_OPTIONS = deps.IDEA_COUNT_OPTIONS
    IDEA_EMOTION_OPTIONS = deps.IDEA_EMOTION_OPTIONS
    IDEA_GENRES = deps.IDEA_GENRES
    IDEA_GENERATION_PROGRESS_PULSE_SECONDS = deps.IDEA_GENERATION_PROGRESS_PULSE_SECONDS
    IDEA_LAB_UI_TIMEOUT_SECONDS = deps.IDEA_LAB_UI_TIMEOUT_SECONDS
    IDEA_SORT_OPTIONS = deps.IDEA_SORT_OPTIONS
    OPERATION_CANCELLED_MESSAGE = deps.OPERATION_CANCELLED_MESSAGE
    STORY_DURATION_OPTIONS = deps.STORY_DURATION_OPTIONS
    block_if_missing_api_keys_for_step = deps.block_if_missing_api_keys_for_step
    coerce_duration_minutes = deps.coerce_duration_minutes
    filter_ideas = deps.filter_ideas
    friendly_ai_error = deps.friendly_ai_error
    generate_freeform_idea_batches = deps.generate_freeform_idea_batches
    generation_progress_dialog = deps.generation_progress_dialog
    has_idea_filters = deps.has_idea_filters
    idea_active_filter_labels = deps.idea_active_filter_labels
    load_saved_ideas = deps.load_saved_ideas
    mark_dialog_task_cancelable = deps.mark_dialog_task_cancelable
    play_completion_sound = deps.play_completion_sound
    replace_generated_ideas = deps.replace_generated_ideas
    safe_close_ui_element = deps.safe_close_ui_element
    safe_notify = deps.safe_notify
    save_idea = deps.save_idea
    show_ai_error_popup = deps.show_ai_error_popup
    unique_idea_filter_options = deps.unique_idea_filter_options
    _idea_generation_progress_detail = deps._idea_generation_progress_detail
    _pulse_idea_generation_progress = deps._pulse_idea_generation_progress

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
                        3,
                        "ideia",
                        _idea_generation_progress_detail(0, 3),
                    )
                )

                async def generate() -> None:
                    if block_if_missing_api_keys_for_step("ideas"):
                        return
                    expected_count = int(idea_count_select.value or 3)
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
                    mark_dialog_task_cancelable(idea_generation_dialog)
                    update_idea_generation_progress(
                        0,
                        expected_count,
                        _idea_generation_progress_detail(0, expected_count),
                    )
                    try:
                        replace_generated_ideas([])
                        generated: list[dict[str, Any]] = []
                        async with asyncio.timeout(IDEA_LAB_UI_TIMEOUT_SECONDS):
                            async for batch in generate_freeform_idea_batches(
                                "",
                                count=expected_count,
                                genre=str(genre_select.value or ""),
                                primary_emotion=str(emotion_select.value or ""),
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
                        safe_notify(
                            f"{len(generated)} ideia(s) gerada(s) e salva(s).",
                            color="positive",
                        )
                        play_completion_sound()
                    except TimeoutError:
                        show_ai_error_popup(
                            "A geração demorou demais. Tente novamente ou escolha outro modelo.",
                            title="A IA demorou demais",
                        )
                    except asyncio.CancelledError:
                        safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
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
                    emotion_select = (
                        ui.select(
                            IDEA_EMOTION_OPTIONS,
                            label="Emoção principal",
                            value=IDEA_EMOTION_OPTIONS[0],
                        )
                        .props("outlined")
                        .classes("w-52")
                    )
                    idea_count_select = (
                        ui.select(
                            IDEA_COUNT_OPTIONS,
                            label="Quantidade",
                            value=3,
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
                safe_notify("Ideia apagada definitivamente.", color="warning")

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
