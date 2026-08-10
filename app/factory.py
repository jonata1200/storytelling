import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.auth.ui_middleware import UIBasicAuthMiddleware
from app.auth.ui_routes import router as auth_ui_router
from app.config.settings import get_settings, insecure_default_secret_key_warning
from app.observability.middleware import CorrelationIdMiddleware
from app.runtime import install_asyncio_exception_filter
from app.workflows.state_machine import WorkflowStateError

LOCAL_STORAGE_MOUNT_ENVS = {"local", "development", "test"}
LOCAL_DOCS_ENVS = {"local", "development", "test"}
logger = logging.getLogger(__name__)


def create_app(include_ui: bool = True) -> FastAPI:
    settings = get_settings()
    secret_key_warning = insecure_default_secret_key_warning()
    if secret_key_warning:
        logger.warning(secret_key_warning)
    docs_enabled = settings.app_env.lower() in LOCAL_DOCS_ENVS
    app = FastAPI(
        title=settings.app_name,
        debug=settings.app_debug,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(UIBasicAuthMiddleware)
    app.include_router(api_router)
    app.include_router(auth_ui_router)
    app.router.on_startup.append(install_asyncio_exception_filter)

    from app.jobs.service import schedule_stale_job_recovery

    app.router.on_startup.append(schedule_stale_job_recovery)

    @app.get("/static/widget.js", include_in_schema=False)
    async def empty_injected_widget_script() -> Response:
        return Response(content="", media_type="application/javascript")

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
            StaticFiles(directory=Path(__file__).parent / "ui" / "static"),
            name="ui-assets",
        )
        if settings.app_env.lower() in LOCAL_STORAGE_MOUNT_ENVS:
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
            favicon=Path(__file__).parent / "ui" / "static" / "favicon.png",
            language="pt-BR",
            dark=None,
            storage_secret=settings.app_secret_key,
        )
    return app
