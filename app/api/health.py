"""Endpoints de health-check: liveness e readiness agregado dos componentes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.database.session import get_session
from app.observability.service import readiness_dashboard

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    try:
        dashboard = await readiness_dashboard(session, settings)
    except Exception:
        # Se uma dependência (banco/redis) estiver indisponível, reporta estado
        # degradado em vez de deixar o health check retornar 500.
        return {"status": "degraded"}
    return {"status": dashboard.status}
