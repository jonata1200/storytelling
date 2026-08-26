# ruff: noqa: E501, F841

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

ProjectCardsLoader = Callable[[], Awaitable[list[Any]]]
ProjectCardRenderer = Callable[[Any, str], None]
BodyStyle = Callable[[], None]


async def render_projects_page(
    *,
    body_style: BodyStyle,
    project_cards: ProjectCardsLoader,
    render_project_card: ProjectCardRenderer,
    home_sidebar: Callable[[str], None],
    studio_logo: Callable[[], None],
    theme_toggle: Callable[[], Any],
) -> None:
    from app.ui.routes import home_pages as deps

    ui = deps.ui
    PROJECT_SORT_OPTIONS = deps.PROJECT_SORT_OPTIONS
    PROJECT_STAGE_FILTER_OPTIONS = deps.PROJECT_STAGE_FILTER_OPTIONS
    PROJECT_STATUS_FILTER_OPTIONS = deps.PROJECT_STATUS_FILTER_OPTIONS
    PROJECT_UPDATED_FILTER_OPTIONS = deps.PROJECT_UPDATED_FILTER_OPTIONS
    filter_projects = deps.filter_projects
    has_project_filters = deps.has_project_filters
    project_active_filter_labels = deps.project_active_filter_labels

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

