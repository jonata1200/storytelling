"""Ponto de entrada ASGI da aplicação.

Exporta ``app`` para servidores ASGI (uvicorn, Hypercorn). A política de
event loop do Windows é configurada de forma adiada para evitar efeitos
colaterais quando módulos de teste importam app.main.
"""

from fastapi import FastAPI

from app.factory import create_app


def _configure_and_create_app() -> FastAPI:
    """Create the app with Windows event loop policy configured.

    The policy is configured here (not at import time) to avoid side effects
    when modules like tests or tooling import app.main incidentally.
    """
    from app.runtime import configure_windows_event_loop_policy

    configure_windows_event_loop_policy()
    return create_app()


app = _configure_and_create_app()
