from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.auth.ui_middleware import UIBasicAuthMiddleware
from app.auth.ui_routes import router as ui_auth_router
from app.config.settings import get_settings
from app.observability.middleware import CorrelationIdMiddleware
from app.workflows.state_machine import WorkflowStateError


def create_app(include_ui: bool = True) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.app_debug)
    app.add_middleware(CorrelationIdMiddleware)
    if include_ui:
        app.add_middleware(UIBasicAuthMiddleware)
        app.include_router(ui_auth_router)
    app.include_router(api_router)

    @app.exception_handler(WorkflowStateError)
    async def workflow_state_error_handler(
        _request: Request, exc: WorkflowStateError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    if include_ui:
        from nicegui import ui

        from app.ui.pages import register_ui_pages

        settings.local_storage_path.mkdir(parents=True, exist_ok=True)
        app.mount(
            "/ui-assets",
            StaticFiles(directory=Path(__file__).parent / "ui"),
            name="ui-assets",
        )
        app.mount(
            "/storage",
            StaticFiles(directory=settings.local_storage_path),
            name="storage",
        )
        register_ui_pages()
        ui.run_with(
            app,
            mount_path="/",
            title=settings.app_name,
            favicon=Path(__file__).parent / "ui" / "favicon.png",
            language="pt-BR",
            dark=None,
            storage_secret=settings.app_secret_key,
        )
    return app
