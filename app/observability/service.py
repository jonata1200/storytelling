import asyncio
import logging
from collections import Counter
from decimal import Decimal
from typing import Any
from uuid import UUID

from redis.asyncio import Redis, from_url
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.provider_policy import (
    SUPPORTED_AI_PROVIDERS,
    ProviderChannel,
    effective_provider_for_channel,
    provider_api_key,
    provider_channel_base_url,
    provider_display_name,
    provider_model,
    provider_requires_api_key,
)
from app.config.settings import Settings, get_settings
from app.generation.models import PromptExecution, PromptTemplate
from app.observability.middleware import current_correlation_id
from app.observability.models import OperationalEvent
from app.observability.redaction import redact_mapping, redact_secrets
from app.observability.schemas import (
    JobExecutionRead,
    OperationalBreakdownRead,
    OperationalEventCreate,
    OperationalEventRead,
    ProjectExecutionSummaryRead,
    ProjectOperationalSummaryRead,
    PromptExecutionRead,
    PromptExecutionTaskMetricsRead,
    ProviderChannelHealthRead,
    ReadinessComponentRead,
    ReadinessDashboardRead,
)
from app.providers.media_utils import resolve_ffmpeg_path
from app.video_generation.models import GenerationJob

logger = logging.getLogger(__name__)

_shared_redis: Redis | None = None


def _get_shared_redis(url: str) -> Redis:
    global _shared_redis
    if _shared_redis is None or _shared_redis.connection_pool.connection_kwargs.get("url") != url:
        _shared_redis = from_url(url)
    return _shared_redis


def _cost(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.000001"))


OPERATIONAL_EVENT_MESSAGE_MAX_LENGTH = 2000


async def emit_project_event(
    session: AsyncSession,
    data: OperationalEventCreate,
) -> OperationalEvent:
    # Truncate message to the schema max_length to ensure consistency between
    # API-created events (validated by Pydantic) and service-layer events.
    raw_message = redact_secrets(data.message)
    truncated_message = raw_message[:OPERATIONAL_EVENT_MESSAGE_MAX_LENGTH]
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
        message=truncated_message,
        details=redact_mapping(data.details),
    )
    session.add(event)
    # Flush to ensure the event is written within the current transaction,
    # so callers that raise after emit (e.g. assert_project_budget_allows)
    # don't lose the audit event if the caller catches and rolls back.
    await session.flush()
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
        OperationalBreakdownRead(key=key, count=count) for key, count in sorted(counter.items())
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


async def provider_channel_health(
    session: AsyncSession,
    *,
    limit: int = 10,
) -> list[ProviderChannelHealthRead]:
    """Últimas N gerações por canal de provedor, com contagem de falhas (ARQ-03).

    Consulta `operational_events` de tipo `worker_job` (emitidos pelo worker a
    cada geração IMAGE/VIDEO) e agrega por canal: Meta AI (imagem) e Vibes
    (vídeo). Responde "últimas 10 gerações: quantas falharam e por quê" sem
    precisar abrir o banco manualmente.
    """
    result = await session.execute(
        select(OperationalEvent)
        .where(
            OperationalEvent.event_type == "worker_job",
            OperationalEvent.provider.in_(("meta", "vibes")),
        )
        .order_by(OperationalEvent.created_at.desc())
        .limit(limit * 20)
    )
    events = list(result.scalars())

    channels: dict[str, list[OperationalEvent]] = {"meta": [], "vibes": []}
    for event in events:
        provider = str(event.provider or "").lower()
        if provider in channels and len(channels[provider]) < limit:
            channels[provider].append(event)

    health: list[ProviderChannelHealthRead] = []
    for provider, channel_events in channels.items():
        total = len(channel_events)
        failures = sum(1 for event in channel_events if event.status.lower() == "failed")
        session_failures = [
            event
            for event in channel_events
            if event.status.lower() == "failed"
            and (
                "autoriz" in event.message.lower()
                or "sessão" in event.message.lower()
                or "sessao" in event.message.lower()
                or "login" in event.message.lower()
            )
        ]
        health.append(
            ProviderChannelHealthRead(
                provider=provider,
                recent_total=total,
                recent_failures=failures,
                recent_session_failures=len(session_failures),
                latest_message=channel_events[0].message[:200] if channel_events else None,
                latest_status=channel_events[0].status if channel_events else None,
                latest_event_at=channel_events[0].created_at if channel_events else None,
            )
        )
    return health


def _prompt_task(execution: PromptExecution, template_task: str | None) -> str:
    if template_task:
        return template_task
    for key in ("task", "stage", "operation"):
        value = execution.variables.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"


def _job_step(job: GenerationJob) -> str | None:
    step = job.request_payload.get("step")
    return str(step) if isinstance(step, str) and step else None


def _payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    details = redact_mapping(payload)
    summary: dict[str, Any] = {}
    for key in (
        "step",
        "frame_number",
        "duration_seconds",
        "variant_index",
        "provider",
        "model",
        "aspect_ratio",
        "size",
        "request_fingerprint",
    ):
        if key in details:
            summary[key] = details[key]
    nested_payload = details.get("payload")
    if isinstance(nested_payload, dict):
        summary["payload_keys"] = sorted(str(key) for key in nested_payload)[:20]
    prompt = details.get("prompt") or details.get("video_prompt")
    if prompt:
        prompt_text = str(prompt)
        summary["prompt_preview"] = prompt_text[:180]
        summary["prompt_chars"] = len(prompt_text)
    return summary or details


async def project_execution_summary(
    session: AsyncSession,
    project_id: UUID,
    *,
    prompt_limit: int = 50,
    job_limit: int = 50,
) -> ProjectExecutionSummaryRead:
    prompt_result = await session.execute(
        select(PromptExecution, PromptTemplate.task)
        .outerjoin(PromptTemplate, PromptExecution.prompt_template_id == PromptTemplate.id)
        .where(PromptExecution.project_id == project_id)
        .order_by(PromptExecution.created_at.desc())
        .limit(prompt_limit)
    )
    prompt_rows = list(prompt_result.all())
    prompt_reads: list[PromptExecutionRead] = []
    metrics: dict[str, dict[str, Any]] = {}
    for execution, template_task in prompt_rows:
        task = _prompt_task(execution, template_task)
        prompt_reads.append(
            PromptExecutionRead(
                id=execution.id,
                artifact_id=execution.artifact_id,
                task=task,
                provider=execution.provider,
                model=execution.model,
                duration_ms=execution.duration_ms,
                estimated_cost=execution.estimated_cost,
                created_at=execution.created_at,
            )
        )
        bucket = metrics.setdefault(
            task,
            {
                "count": 0,
                "duration_total": 0,
                "duration_count": 0,
                "max_duration_ms": None,
                "estimated_cost": Decimal("0.000000"),
                "latest_at": None,
            },
        )
        bucket["count"] += 1
        bucket["estimated_cost"] += Decimal(execution.estimated_cost or 0)
        if execution.duration_ms is not None:
            bucket["duration_total"] += execution.duration_ms
            bucket["duration_count"] += 1
            bucket["max_duration_ms"] = max(
                int(bucket["max_duration_ms"] or 0),
                execution.duration_ms,
            )
        latest_at = bucket["latest_at"]
        if latest_at is None or execution.created_at > latest_at:
            bucket["latest_at"] = execution.created_at

    job_result = await session.execute(
        select(GenerationJob)
        .where(GenerationJob.project_id == project_id)
        .order_by(GenerationJob.created_at.desc())
        .limit(job_limit)
    )
    recent_jobs = [
        JobExecutionRead(
            id=job.id,
            job_type=str(job.job_type.value),
            step=_job_step(job),
            status=str(job.status.value),
            progress=job.progress,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            provider=job.provider,
            model=job.model,
            external_job_id=job.external_job_id,
            estimated_cost=Decimal(job.cost_estimate or 0),
            error=redact_secrets(job.error),
            request_payload_summary=_payload_summary(job.request_payload or {}),
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )
        for job in job_result.scalars()
    ]
    prompt_metrics = [
        PromptExecutionTaskMetricsRead(
            task=task,
            count=int(bucket["count"]),
            average_duration_ms=(
                int(bucket["duration_total"] / bucket["duration_count"])
                if bucket["duration_count"]
                else None
            ),
            max_duration_ms=bucket["max_duration_ms"],
            estimated_cost=Decimal(bucket["estimated_cost"]).quantize(Decimal("0.000001")),
            latest_at=bucket["latest_at"],
        )
        for task, bucket in sorted(metrics.items())
    ]
    return ProjectExecutionSummaryRead(
        project_id=project_id,
        prompt_executions=prompt_reads,
        prompt_metrics=prompt_metrics,
        recent_jobs=recent_jobs,
    )


async def _redis_check(name: str, url: str) -> ReadinessComponentRead:
    redis = _get_shared_redis(url)
    try:
        await asyncio.wait_for(redis.ping(), timeout=5.0)
    except Exception as exc:
        return ReadinessComponentRead(
            name=name,
            status="down",
            message=redact_secrets(exc),
        )
    return ReadinessComponentRead(name=name, status="ready", message="Redis respondeu ao ping")


async def _worker_heartbeat_check(settings: Settings) -> ReadinessComponentRead:
    """Verifica se algum worker publicou heartbeat recente no Redis.

    Workers ativos gravam `<queue>:heartbeat:<consumer>` com TTL de
    ``worker_heartbeat_seconds * 3``; ausência da chave indica worker parado.
    """
    redis = _get_shared_redis(settings.redis_url)
    try:
        keys = await asyncio.wait_for(
            redis.keys(f"{settings.worker_queue_name}:heartbeat:*"), timeout=5.0
        )
    except Exception as exc:
        return ReadinessComponentRead(
            name="media_worker",
            status="degraded",
            message=f"Não foi possível consultar heartbeat do worker: {redact_secrets(exc)}",
        )
    count = len([k for k in keys if k])
    if count == 0:
        return ReadinessComponentRead(
            name="media_worker",
            status="degraded",
            message="Nenhum heartbeat de worker ativo; jobs de mídia não serão processados.",
        )
    return ReadinessComponentRead(
        name="media_worker",
        status="ready",
        message=f"{count} worker(s) com heartbeat recente",
    )


def _provider_model_env_name(provider: str, channel: ProviderChannel) -> str:
    suffix_by_channel = {
        "text": "DEFAULT_MODEL",
        "image": "IMAGE_MODEL",
        "video": "VIDEO_MODEL",
    }
    return f"{provider.upper()}_{suffix_by_channel[channel]}"


def _provider_channel_readiness(
    settings: Settings,
    channel: ProviderChannel,
) -> ReadinessComponentRead:
    provider = effective_provider_for_channel(settings, channel)
    display_name = provider_display_name(provider)
    api_key = provider_api_key(settings, provider)
    model = provider_model(settings, provider, channel)
    base_url = provider_channel_base_url(settings, provider, channel)
    missing: list[str] = []
    if provider_requires_api_key(settings, provider) and not api_key:
        missing.append(
            "OLLAMA_API_KEY"
            if provider == "ollama_cloud"
            else f"{provider.upper()}_API_KEY"
        )
    if not model:
        missing.append(_provider_model_env_name(provider, channel))
    if provider_requires_api_key(settings, provider) and not base_url:
        endpoint_field = f"{provider}_{channel}_endpoint"
        base_field = f"{provider}_{channel}_base_url"
        if hasattr(settings, endpoint_field):
            missing.append(endpoint_field.upper())
        elif hasattr(settings, base_field):
            missing.append(base_field.upper())
        else:
            missing.append(f"{provider.upper()}_BASE_URL")
    if (
        channel == "image"
        and provider == "meta"
        and not bool(getattr(settings, "meta_browser_automation_enabled", False))
    ):
        missing.append("META_BROWSER_AUTOMATION_ENABLED")
    if (
        channel == "video"
        and provider == "vibes"
        and not bool(getattr(settings, "vibes_browser_automation_enabled", False))
    ):
        missing.append("VIBES_BROWSER_AUTOMATION_ENABLED")

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
            "base_url": base_url,
            "api_key_configured": str(bool(api_key)).lower(),
            "fallbacks": (
                str(getattr(settings, "text_provider_fallbacks", "") or "")
                if channel == "text"
                else ""
            ),
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
    components.append(await _worker_heartbeat_check(app_settings))
    ffmpeg_path = resolve_ffmpeg_path(app_settings.ffmpeg_path)
    components.append(
        ReadinessComponentRead(
            name="ffmpeg",
            status="ready" if ffmpeg_path else "degraded",
            message="FFmpeg encontrado" if ffmpeg_path else "FFmpeg não encontrado",
            details={"path": ffmpeg_path},
        )
    )
    components.extend(
        _provider_channel_readiness(app_settings, channel) for channel in ("text", "image", "video")
    )
    overall = "ready" if all(item.status == "ready" for item in components) else "degraded"
    if any(item.status == "down" for item in components):
        overall = "down"
    return ReadinessDashboardRead(status=overall, components=components)
