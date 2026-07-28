import asyncio
import logging
import shutil
from collections import Counter
from decimal import Decimal
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.provider_policy import (
    SUPPORTED_AI_PROVIDERS,
    effective_provider_for_channel,
    provider_api_key,
    provider_base_url,
    provider_display_name,
    provider_model,
)
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
from app.providers.speech.service import speech_configuration_status

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
            "provider": data.provider,
            "model": data.model,
            "operation": data.operation,
            "estimated_cost": str(_cost(data.estimated_cost) or ""),
            "actual_cost": str(_cost(data.actual_cost) or ""),
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


def _provider_model_env_name(provider: str, channel: str) -> str:
    suffix_by_channel = {
        "text": "DEFAULT_MODEL",
        "image": "IMAGE_MODEL",
        "video": "VIDEO_MODEL",
    }
    return f"{provider.upper()}_{suffix_by_channel[channel]}"


def _provider_channel_readiness(settings: Settings, channel: str) -> ReadinessComponentRead:
    provider = effective_provider_for_channel(settings, channel)  # type: ignore[arg-type]
    display_name = provider_display_name(provider)
    api_key = provider_api_key(settings, provider)
    model = provider_model(settings, provider, channel)  # type: ignore[arg-type]
    missing: list[str] = []
    if not api_key:
        missing.append(f"{provider.upper()}_API_KEY")
    if not model:
        missing.append(_provider_model_env_name(provider, channel))

    labels = {
        "text": "texto",
        "image": "imagem",
        "video": "vídeo",
    }
    channel_label = labels[channel]
    ready = not missing
    message = (
        f"{display_name} pronto para {channel_label}"
        if ready
        else f"Configure {', '.join(missing)} para {channel_label}"
    )
    return ReadinessComponentRead(
        name=f"{channel}_provider",
        status="ready" if ready else "degraded",
        message=message,
        details={
            "provider": provider,
            "model": model,
            "base_url": provider_base_url(settings, provider),
            "api_key_configured": str(bool(api_key)).lower(),
            "supported_providers": ", ".join(SUPPORTED_AI_PROVIDERS),
        },
    )


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
            message="FFmpeg encontrado" if ffmpeg_path else "FFmpeg não encontrado no PATH",
            details={"path": ffmpeg_path},
        )
    )
    components.extend(
        _provider_channel_readiness(app_settings, channel)
        for channel in ("text", "image", "video")
    )
    speech_ready, speech_message, speech_details = speech_configuration_status(app_settings)
    components.append(
        ReadinessComponentRead(
            name="character_speech",
            status="ready" if speech_ready else "degraded",
            message=speech_message,
            details=speech_details,
        )
    )
    overall = "ready" if all(item.status == "ready" for item in components) else "degraded"
    if any(item.status == "down" for item in components):
        overall = "down"
    return ReadinessDashboardRead(status=overall, components=components)
