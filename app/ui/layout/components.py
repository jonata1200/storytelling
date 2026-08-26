from nicegui import ui

from app.ui.layout.navigation import theme_toggle


def card_classes(extra: str = "") -> str:
    return f"entity-card rounded-lg shadow-none {extra}".strip()


def button_classes() -> str:
    return "studio-primary-button font-semibold rounded-lg"


def muted(text: str) -> None:
    ui.label(text).classes("text-sm text-slate-400")


def render_header(title: str, subtitle: str) -> None:
    with ui.row().classes(
        "w-full items-center justify-between px-6 py-4 bg-slate-900 border-b border-slate-800"
    ):
        with ui.row().classes("items-center gap-3"):
            ui.icon("movie_filter").classes("text-3xl text-cyan-300")
            with ui.column().classes("gap-0"):
                ui.label(title).classes("text-2xl font-bold")
                ui.label(subtitle).classes("text-sm text-slate-400")
        with ui.row().classes("gap-2"):
            theme_toggle()
            ui.button(
                "Projetos", icon="dashboard", on_click=lambda: ui.navigate.to("/projects")
            ).classes("bg-slate-800 hover:bg-slate-700 rounded-md")
            ui.link("API docs", "/docs").classes(
                "text-slate-100 bg-slate-800 hover:bg-slate-700 px-3 py-2 rounded-md"
            )
