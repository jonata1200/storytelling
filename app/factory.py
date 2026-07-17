from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config.settings import get_settings
from app.observability.middleware import CorrelationIdMiddleware


def create_app(include_ui: bool = True) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.app_debug)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(api_router)
    if include_ui:
        from nicegui import ui

        from app.ui.pages import register_ui_pages

        app.mount(
            "/ui-assets",
            StaticFiles(directory=Path(__file__).parent / "ui"),
            name="ui-assets",
        )
        register_ui_pages()
        ui.run_with(app, mount_path="/")
    return app
