"""Fábrica da aplicação FastAPI.

Monta a app com routers, middleware de correlação, tratamento de erros de
transição de workflow e o mount de arquivos estáticos de storage (somente em
ambientes locais). A UI NiceGUI é acoplada opcionalmente via ``include_ui``.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config.settings import get_settings
from app.observability.middleware import CorrelationIdMiddleware
from app.runtime import install_asyncio_exception_filter
from app.workflows.state_machine import WorkflowStateError

LOCAL_STORAGE_MOUNT_ENVS = {"local", "development", "test"}
LOCAL_DOCS_ENVS = {"local", "development", "test"}
logger = logging.getLogger(__name__)


def create_app(include_ui: bool = True) -> FastAPI:
    settings = get_settings()
    local_environment = settings.app_env.lower() in LOCAL_DOCS_ENVS
    docs_enabled = local_environment
    ui_enabled = include_ui and local_environment
    if include_ui and not ui_enabled:
        logger.warning(
            "ui_disabled_in_non_local_environment app_env=%s; "
            "serve the UI behind an authenticated local deployment",
            settings.app_env,
        )
    app = FastAPI(
        title=settings.app_name,
        debug=settings.app_debug,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(api_router)
    app.router.on_startup.append(install_asyncio_exception_filter)

    from app.jobs.service import schedule_stale_job_recovery

    app.router.on_startup.append(schedule_stale_job_recovery)

    async def _migrate_persisted_generate_script_template() -> None:
        # Migra templates generate_script persistidos com a instrução
        # antiga (que proibia a IA de nomear o roteiro). Idempotente e
        # seguro para customizações do operador: só atualiza se a
        # instrução antiga estiver presente no template persistido.
        from app.database.session import AsyncSessionLocal
        from app.generation.service import (
            migrate_persisted_generate_script_template,
        )

        async with AsyncSessionLocal() as session:
            try:
                await migrate_persisted_generate_script_template(session)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "template_inline_migration_failed: %s", exc
                )

    app.router.on_startup.append(_migrate_persisted_generate_script_template)

    async def _dispose_engine_on_shutdown() -> None:
        from app.database.session import dispose_engine

        await dispose_engine()

    app.router.on_shutdown.append(_dispose_engine_on_shutdown)

    @app.get("/static/widget.js", include_in_schema=False)
    async def empty_injected_widget_script() -> Response:
        return Response(content="", media_type="application/javascript")

    @app.exception_handler(WorkflowStateError)
    async def workflow_state_error_handler(
        _request: Request, exc: WorkflowStateError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    if ui_enabled:
        from nicegui import ui

        from app.ui import pages as ui_pages
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
        register_ui_pages(ui_pages)
        ui.run_with(
            app,
            mount_path="/",
            title=settings.app_name,
            favicon=Path(__file__).parent / "ui" / "static" / "favicon.png",
            language="pt-BR",
            dark=(settings.user_theme == "dark"),
            storage_secret=settings.app_secret_key,
        )
    return app
