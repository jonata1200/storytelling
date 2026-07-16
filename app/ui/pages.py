from nicegui import ui

from app.config.settings import get_settings


def register_ui_pages() -> None:
    settings = get_settings()

    @ui.page("/")
    def dashboard() -> None:
        ui.query("body").classes("bg-slate-950 text-slate-100")
        with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-6"):
            ui.label(settings.app_name).classes("text-3xl font-bold")
            ui.label("Pipeline inicial de producao audiovisual").classes("text-slate-300")

            with ui.row().classes("w-full gap-4"):
                for title, status in [
                    ("Fundacao", "em andamento"),
                    ("Dominio", "proximo"),
                    ("Narrativa", "aguardando"),
                    ("Storyboard", "aguardando"),
                ]:
                    with ui.card().classes("w-56 bg-slate-900 border border-slate-800"):
                        ui.label(title).classes("text-lg font-semibold")
                        ui.label(status).classes("text-sm text-slate-400")

            ui.link("API health", "/api/v1/health/live").classes("text-blue-300")
