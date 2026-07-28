import asyncio
import logging
import shutil
from collections import Counter
from decimal import Decimal
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.observability.middleware import current_correlation_id
from app.observability.models import OperationalEvent
from app.observability.redaction import redact_mapping, redact_secrets
from app.observability.schemas import (
    OperationalBreakdownRead,
    OperationalEventCreate,
    OperationalEventRead,
    ProjectOperationalSummaryRead,
    ReadinessComponentRead,
    ReadinessDashboardRead,
)

logger = logging.getLogger(__name__)


def _cost(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.000001"))


async def emit_project_event(
    session: AsyncSession,
    data: OperationalEventCreate,
) -> OperationalEvent:
    event = OperationalEvent(
        project_id=data.project_id,
        artifact_id=data.artifact_id,
        job_id=data.job_id,
        event_type=data.event_type,
        status=data.status,
        actor=data.actor,
        provider=data.provider,
        model=data.model,
        operation=data.operation,
        correlation_id=current_correlation_id(),
        estimated_cost=_cost(data.estimated_cost),
        actual_cost=_cost(data.actual_cost),
        message=redact_secrets(data.message),
        details=redact_mapping(data.details),
    )
    session.add(event)
    logger.info(
        "operational_event",
        extra={
            "project_id": str(data.project_id),
            "event_type": data.event_type,
            "status": data.status,
            "correlation_id": event.correlation_id,
        },
    )
    return event


async def list_project_events(
    session: AsyncSession,
    project_id: UUID,
    limit: int = 100,
) -> list[OperationalEvent]:
    result = await session.execute(
        select(OperationalEvent)
        .where(OperationalEvent.project_id == project_id)
        .order_by(OperationalEvent.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars())


def _breakdown(counter: Counter[str]) -> list[OperationalBreakdownRead]:
    return [
        OperationalBreakdownRead(key=key, count=count)
        for key, count in sorted(counter.items())
    ]


async def project_operational_summary(
    session: AsyncSession,
    project_id: UUID,
) -> ProjectOperationalSummaryRead:
    events = await list_project_events(session, project_id, limit=500)
    failures = sum(1 for event in events if event.status.lower() in {"failed", "error"})
    return ProjectOperationalSummaryRead(
        project_id=project_id,
        total_events=len(events),
        failures=failures,
        by_status=_breakdown(Counter(event.status for event in events)),
        by_event_type=_breakdown(Counter(event.event_type for event in events)),
        latest_events=[OperationalEventRead.model_validate(event) for event in events[:20]],
    )


async def _redis_check(name: str, url: str) -> ReadinessComponentRead:
    redis = Redis.from_url(url)
    try:
        await asyncio.wait_for(redis.ping(), timeout=1.5)
    except Exception as exc:
        return ReadinessComponentRead(
            name=name,
            status="down",
            message=redact_secrets(exc),
        )
    finally:
        await redis.aclose()
    return ReadinessComponentRead(name=name, status="ready", message="Redis respondeu ao ping")


async def readiness_dashboard(
    session: AsyncSession,
    settings: Settings | None = None,
) -> ReadinessDashboardRead:
    app_settings = settings or get_settings()
    components: list[ReadinessComponentRead] = [
        ReadinessComponentRead(
            name="api",
            status="ready",
            message=f"{app_settings.app_name} em {app_settings.app_env}",
        )
    ]
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        components.append(
            ReadinessComponentRead(name="database", status="down", message=redact_secrets(exc))
        )
    else:
        components.append(
            ReadinessComponentRead(name="database", status="ready", message="Banco respondeu")
        )

    components.append(await _redis_check("redis", app_settings.redis_url))
    components.append(await _redis_check("worker_broker", app_settings.celery_broker_url))
    ffmpeg_path = shutil.which("ffmpeg")
    components.append(
        ReadinessComponentRead(
            name="ffmpeg",
            status="ready" if ffmpeg_path else "degraded",
            message="FFmpeg encontrado" if ffmpeg_path else "FFmpeg nao encontrado no PATH",
            details={"path": ffmpeg_path},
        )
    )
    components.append(
        ReadinessComponentRead(
            name="openrouter",
            status="ready" if app_settings.openrouter_api_key else "degraded",
            message=(
                "Chave OpenRouter configurada"
                if app_settings.openrouter_api_key
                else "OPENROUTER_API_KEY ausente"
            ),
        )
    )
    overall = "ready" if all(item.status == "ready" for item in components) else "degraded"
    if any(item.status == "down" for item in components):
        overall = "down"
    return ReadinessDashboardRead(status=overall, components=components)
