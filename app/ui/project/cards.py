from collections.abc import Awaitable, Callable
from uuid import UUID

from nicegui import ui

from app.projects.models import Project


def render_project_card(
    project: Project,
    redirect_to: str,
    rename_project: Callable[[UUID, str, str], Awaitable[None]],
    delete_project: Callable[[UUID, str], Awaitable[None]],
) -> None:
    with ui.dialog() as rename_dialog, ui.card().classes("entity-card rounded-2xl p-6 min-w-96"):
        ui.label("Renomear projeto").classes("brand-type text-2xl font-bold")
        name_input = (
            ui.input("Nome do projeto", value=project.title).props("outlined").classes("w-full")
        )
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancelar", on_click=rename_dialog.close).props("flat no-caps")
            ui.button(
                "Salvar",
                icon="save",
                on_click=lambda p=project.id: rename_project(
                    p, str(name_input.value or ""), redirect_to
                ),
            ).props("unelevated no-caps").classes("acid-bg rounded-xl")

    with ui.dialog() as delete_dialog, ui.card().classes("entity-card rounded-2xl p-6 min-w-96"):
        ui.label("Excluir projeto?").classes("brand-type text-2xl font-bold")
        ui.label(f'O projeto "{project.title}" será removido da lista de projetos.').classes(
            "text-sm text-[#8d938e]"
        )
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancelar", on_click=delete_dialog.close).props("flat no-caps")
            ui.button(
                "Excluir",
                icon="delete",
                on_click=lambda p=project.id: delete_project(p, redirect_to),
            ).props("unelevated no-caps").classes("bg-red-600 text-white rounded-xl")

    with (
        ui.element("article")
        .classes("entity-card rounded-2xl overflow-hidden cursor-pointer")
        .on("click", lambda p=project.id: ui.navigate.to(f"/projects/{p}/script"))
    ):
        with ui.element("div").classes("visual-placeholder aspect-video p-5 flex items-end"):
            ui.icon("play_circle").classes("text-4xl acid")
        with ui.column().classes("p-4 gap-2"):
            ui.label(project.title).classes("brand-type text-xl font-bold")
            ui.label(project.description or "Projeto em desenvolvimento").classes(
                "text-sm text-[#8d938e] line-clamp-2"
            )
            with ui.row().classes("gap-2 mt-2 flex-wrap"):
                ui.button("Renomear", icon="edit", on_click=rename_dialog.open).props(
                    "flat no-caps"
                ).classes("text-[#aeb3ae]").on("click.stop", lambda: None)
                ui.button("Excluir", icon="delete", on_click=delete_dialog.open).props(
                    "flat no-caps"
                ).classes("text-red-300").on("click.stop", lambda: None)
