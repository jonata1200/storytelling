import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from redis.asyncio import from_url
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.api_keys import require_api_keys_for_creation_step
from app.core.enums import GenerationJobStatus, GenerationJobType, ProjectStep
from app.production.service import get_or_create_production_settings
from app.projects.repository import ProjectRepository
from app.video_generation.models import GenerationJob

logger = logging.getLogger(__name__)

PROJECT_STEP_JOB_TYPES = {
    ProjectStep.INITIAL_SCRIPT: GenerationJobType.ANALYSIS,
    ProjectStep.IDEAS: GenerationJobType.ANALYSIS,
    ProjectStep.SCRIPT: GenerationJobType.ANALYSIS,
    ProjectStep.SCENES: GenerationJobType.ANALYSIS,
    # Nota: as etapas VIDEO/CONTINUOUS_VIDEO não são mais executadas como jobs
    # internos — a produção de vídeo agora prede vídeo
    # (app.video_generation.continuous) sem geração de vídeo por IA.
}

TERMINAL_JOB_STATUSES = {
    GenerationJobStatus.SUCCEEDED,
    GenerationJobStatus.CANCELLED,
}
PENDING_JOB_REDISPATCH_AFTER = timedelta(minutes=2)
RUNNING_JOB_RECLAIM_AFTER = timedelta(minutes=15)

_running_background_tasks: set[asyncio.Task] = set()
_running_project_tasks: dict[UUID, asyncio.Task] = {}


@dataclass(frozen=True)
class JobEnqueueDecision:
    """Resultado do enqueue: o job e se ele deve ser despachado agora.

    Substitui o antigo atributo dinâmico ``_should_dispatch_after_enqueue`` colado no
    modelo SQLAlchemy, que era perdido quando o objeto era relido da sessão.
    """

    job: GenerationJob
    should_dispatch: bool


def normalize_step(value: str) -> ProjectStep | None:
    step = str(value or "").strip().lower().replace("-", "_")
    if step not in PROJECT_STEP_JOB_TYPES:
        return None
    return ProjectStep(step)


def job_idempotency_key(project_id: UUID, step: str | ProjectStep, payload: dict) -> str:
    normalized = normalize_step(step) if isinstance(step, str) else step
    body = {
        "project_id": str(project_id),
        "step": normalized.value if normalized is not None else str(step),
        "payload": payload,
    }
    serialized = json.dumps(body, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def project_job_can_run(job: GenerationJob) -> bool:
    if job.status in TERMINAL_JOB_STATUSES:
        return False
    return not (job.status == GenerationJobStatus.FAILED and job.attempts >= job.max_attempts)


def pending_job_is_stale(job: GenerationJob, now: datetime | None = None) -> bool:
    if job.status != GenerationJobStatus.PENDING:
        return False
    updated_at = job.updated_at or job.created_at
    if updated_at is None:
        return True
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    reference_time = now or datetime.now(UTC)
    return reference_time - updated_at >= PENDING_JOB_REDISPATCH_AFTER


_project_action_last: dict[UUID, dict[str, str | None]] = {}


async def _set_project_job_action(
    session: AsyncSession,
    job: GenerationJob,
    *,
    status: str,
    message: str,
    error: str | None = None,
) -> None:
    # Busca settings sempre frescos (não cacheia no modelo): após um rollback o
    # objeto cacheado ficaria expirado/detached e acessar metadata_json lançaria
    # DetachedInstanceError, mascarando o erro original. O dedup de eventos usa
    # um dict externo chaveado por project_id em vez de atributos ad-hoc.
    settings = await get_or_create_production_settings(session, job.project_id)
    last_action = _project_action_last.get(job.project_id)
    if (
        last_action is not None
        and last_action["status"] == status
        and last_action["message"] == message
        and last_action["error"] == error
    ):
        # Evento identico ao anterior: nao duplica o historico, mas mantem o
        # updated_at fresco para o timeout da UI nao disparar por engano.
        metadata = dict(settings.metadata_json or {})
        previous_action = metadata.get("ai_action")
        if isinstance(previous_action, dict):
            previous_action["updated_at"] = datetime.now(UTC).isoformat()
            settings.metadata_json = metadata
            await session.flush()
        return
    metadata = dict(settings.metadata_json or {})
    action = str(job.request_payload.get("step") or "project_step")
    previous_action = metadata.get("ai_action")
    previous_events = previous_action.get("events", []) if isinstance(previous_action, dict) else []
    events = [event for event in previous_events if isinstance(event, dict)]
    events.append(
        {
            "id": f"{action}:{len(events) + 1}",
            "action": action,
            "status": status,
            "message": message,
            "job_id": str(job.id),
        }
    )
    metadata["ai_action"] = {
        "action": action,
        "status": status,
        "message": message,
        "error": error,
        "job_id": str(job.id),
        "updated_at": datetime.now(UTC).isoformat(),
        "events": events[-60:],
    }
    settings.metadata_json = metadata
    _project_action_last[job.project_id] = {
        "status": status,
        "message": message,
        "error": error,
    }
    await session.flush()


async def create_or_resume_project_job(
    session: AsyncSession,
    project_id: UUID,
    step: str,
    payload: dict | None = None,
    *,
    provider: str = "system",
    model: str = "pipeline",
    max_attempts: int = 3,
) -> JobEnqueueDecision:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        raise ValueError("Projeto não encontrado.")
    normalized_step = normalize_step(step)
    if normalized_step is None:
        allowed = ", ".join(sorted(PROJECT_STEP_JOB_TYPES))
        raise ValueError(f"Etapa de job inválida: {step or '<vazia>'}. Use: {allowed}.")
    require_api_keys_for_creation_step(normalized_step.value)
    clean_payload = dict(payload or {})
    request_payload = {"step": normalized_step.value, "payload": clean_payload}
    idempotency_key = job_idempotency_key(project_id, normalized_step, clean_payload)
    result = await session.execute(
        select(GenerationJob).where(GenerationJob.idempotency_key == idempotency_key)
    )
    job = result.scalars().first()
    should_dispatch = False
    if job is None:
        job = GenerationJob(
            project_id=project_id,
            job_type=PROJECT_STEP_JOB_TYPES[normalized_step],
            status=GenerationJobStatus.PENDING,
            progress=0,
            attempts=0,
            max_attempts=max_attempts,
            provider=provider,
            model=model,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            response_payload={},
        )
        session.add(job)
        try:
            await session.flush()
        except IntegrityError:
            # Outra requisicao concorrente criou o mesmo job (unique idempotency_key).
            await session.rollback()
            result = await session.execute(
                select(GenerationJob).where(GenerationJob.idempotency_key == idempotency_key)
            )
            job = result.scalars().first()
            if job is None:
                raise
        else:
            should_dispatch = True
    elif job.status == GenerationJobStatus.CANCELLED:
        job.status = GenerationJobStatus.PENDING
        job.progress = 0
        job.error = None
        job.completed_at = None
        job.response_payload = {}
        job.max_attempts = max(job.max_attempts, job.attempts + 1)
        await session.flush()
        should_dispatch = True
    elif job.status == GenerationJobStatus.FAILED and job.attempts < job.max_attempts:
        job.status = GenerationJobStatus.PENDING
        job.progress = 0
        job.error = None
        job.completed_at = None
        job.response_payload = {}
        await session.flush()
        should_dispatch = True
    elif pending_job_is_stale(job):
        should_dispatch = True
    if job.status == GenerationJobStatus.SUCCEEDED:
        action_status = "completed"
        action_message = "Etapa ja concluida anteriormente."
    elif not project_job_can_run(job):
        action_status = "failed"
        action_message = "Etapa falhou e atingiu o limite de tentativas."
    else:
        action_status = "queued"
        action_message = "Etapa agendada para execução interna."
    await _set_project_job_action(
        session,
        job,
        status=action_status,
        message=action_message,
        error=job.error if action_status == "failed" else None,
    )
    await session.commit()
    await session.refresh(job)
    return JobEnqueueDecision(job=job, should_dispatch=should_dispatch)


async def mark_job_running(session: AsyncSession, job: GenerationJob, message: str) -> None:
    job.status = GenerationJobStatus.RUNNING
    job.progress = max(job.progress, 5)
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    job.completed_at = None
    job.error = None
    await _set_project_job_action(session, job, status="running", message=message)
    await session.commit()


async def mark_job_progress(
    session: AsyncSession,
    job: GenerationJob,
    *,
    progress: int,
    message: str,
) -> None:
    job.progress = max(0, min(99, progress))
    await _set_project_job_action(session, job, status="running", message=message)
    await session.commit()


async def mark_job_succeeded(
    session: AsyncSession,
    job: GenerationJob,
    *,
    response_payload: dict | None = None,
    message: str = "Etapa concluida.",
) -> None:
    job.status = GenerationJobStatus.SUCCEEDED
    job.progress = 100
    job.response_payload = response_payload or {}
    job.completed_at = datetime.now(UTC)
    await _set_project_job_action(session, job, status="completed", message=message)
    await session.commit()


async def mark_job_failed(
    session: AsyncSession,
    job: GenerationJob,
    *,
    error: str,
    message: str = "Etapa falhou.",
) -> None:
    job.status = GenerationJobStatus.FAILED
    job.error = error
    job.completed_at = datetime.now(UTC)
    await _set_project_job_action(
        session,
        job,
        status="failed",
        message=message,
        error=error,
    )
    await session.commit()


async def get_job(session: AsyncSession, job_id: UUID) -> GenerationJob | None:
    return await session.get(GenerationJob, job_id)


async def list_project_jobs(session: AsyncSession, project_id: UUID) -> list[GenerationJob]:
    result = await session.execute(
        select(GenerationJob)
        .where(GenerationJob.project_id == project_id)
        .order_by(GenerationJob.created_at.desc())
    )
    return list(result.scalars())


async def create_or_get_media_job(
    session: AsyncSession,
    project_id: UUID,
    *,
    job_type: GenerationJobType,
    operation: str,
    payload: dict[str, Any],
    provider: str,
    model: str,
    attempt_key: str = "initial",
    max_attempts: int = 3,
) -> JobEnqueueDecision:
    if job_type not in {
        GenerationJobType.IMAGE,
        GenerationJobType.VIDEO,
        GenerationJobType.INGREDIENT,
        GenerationJobType.QA,
    }:
        raise ValueError("A fila externa aceita somente jobs de mídia, ingredient ou QA")
    if await ProjectRepository(session).get_project(project_id) is None:
        raise ValueError("Projeto não encontrado.")
    request_payload = {"operation": operation, **dict(payload), "attempt_key": attempt_key}
    key = job_idempotency_key(project_id, operation, request_payload)
    result = await session.execute(
        select(GenerationJob).where(GenerationJob.idempotency_key == key)
    )
    job = result.scalars().first()
    if job is not None:
        should_dispatch = pending_job_is_stale(job)
        if job.status == GenerationJobStatus.FAILED and job.attempts < job.max_attempts:
            job.status = GenerationJobStatus.PENDING
            job.progress = 0
            job.error = None
            job.completed_at = None
            job.response_payload = {}
            await session.commit()
            await session.refresh(job)
            should_dispatch = True
        return JobEnqueueDecision(job=job, should_dispatch=should_dispatch)
    job = GenerationJob(
        project_id=project_id,
        job_type=job_type,
        status=GenerationJobStatus.PENDING,
        progress=0,
        attempts=0,
        max_attempts=max_attempts,
        provider=provider,
        model=model,
        idempotency_key=key,
        request_payload=request_payload,
        response_payload={},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return JobEnqueueDecision(job=job, should_dispatch=True)


async def dispatch_media_job(job: GenerationJob) -> str:
    from app.config.settings import get_settings
    from app.workers.queue import RedisJobQueue

    settings = get_settings()
    redis = from_url(settings.redis_url)
    try:
        queue = RedisJobQueue(
            redis, stream=settings.worker_queue_name, group=settings.worker_consumer_group
        )
        await queue.ensure_group()
        return await queue.enqueue(job.id)
    finally:
        await redis.aclose()


async def cancel_generation_job(
    session: AsyncSession, job_id: UUID
) -> GenerationJob | None:
    job = await session.get(GenerationJob, job_id)
    if job is None:
        return None
    if job.status not in {GenerationJobStatus.SUCCEEDED, GenerationJobStatus.CANCELLED}:
        job.status = GenerationJobStatus.CANCELLED
        job.completed_at = datetime.now(UTC)
        response = dict(job.response_payload or {})
        response["remote_cancellation"] = "unsupported_or_not_attempted"
        response["cancelled_locally_at"] = job.completed_at.isoformat()
        job.response_payload = response
        await session.commit()
        await session.refresh(job)
    task = _running_project_tasks.get(job_id)
    if task is not None and not task.done():
        task.cancel()
    return job


async def retry_generation_job(session: AsyncSession, job_id: UUID) -> GenerationJob | None:
    job = await session.get(GenerationJob, job_id)
    if job is None:
        return None
    if job.status != GenerationJobStatus.FAILED:
        raise ValueError("Somente job com falha pode ser reenfileirado")
    if job.attempts >= job.max_attempts:
        raise ValueError("Job atingiu o limite de tentativas e exige revisão humana")
    job.status = GenerationJobStatus.PENDING
    job.error = None
    job.completed_at = None
    await session.commit()
    await dispatch_media_job(job)
    return job


def dispatch_project_job(job_id: UUID) -> None:
    from app.jobs.runner import run_project_step_job

    async def run_job() -> None:
        try:
            await run_project_step_job(job_id)
        except Exception as exc:
            logger.warning("project_step_background_failed %s: %s", job_id, exc)

    try:
        asyncio.get_running_loop()
    except RuntimeError as exc:
        raise RuntimeError("Não há loop assíncrono ativo para executar a etapa.") from exc
    existing = _running_project_tasks.get(job_id)
    if existing is not None and not existing.done():
        # Já existe uma task ativa para este job. Não criar uma segunda execução
        # concorrente da mesma etapa (evita roteiro/etapa gerado em duplicidade).
        logger.info("project_step_already_running job_id=%s", job_id)
        return
    task = asyncio.create_task(run_job(), name=f"project-step:{job_id}")
    _running_background_tasks.add(task)
    _running_project_tasks[job_id] = task

    def _forget_project_task(done_task: asyncio.Task) -> None:
        _running_background_tasks.discard(done_task)
        if _running_project_tasks.get(job_id) is done_task:
            _running_project_tasks.pop(job_id, None)

    task.add_done_callback(_forget_project_task)


async def enqueue_project_step(
    session: AsyncSession,
    project_id: UUID,
    step: str,
    payload: dict | None = None,
    *,
    dispatch: bool = True,
) -> GenerationJob:
    decision = await create_or_resume_project_job(session, project_id, step, payload)
    job = decision.job
    if dispatch and decision.should_dispatch and project_job_can_run(job):
        dispatch_project_job(job.id)
    return job


def _job_stale_after_window(
    job: GenerationJob,
    window: timedelta,
    now: datetime | None = None,
) -> bool:
    updated_at = job.updated_at or job.created_at
    if updated_at is None:
        return True
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    reference_time = now or datetime.now(UTC)
    return reference_time - updated_at >= window


def _is_recoverable_project_step_job(job: GenerationJob) -> bool:
    payload = getattr(job, "request_payload", None)
    if not isinstance(payload, dict):
        return False
    return normalize_step(str(payload.get("step") or "")) is not None


async def list_stale_pending_jobs(session: AsyncSession, limit: int = 50) -> list[GenerationJob]:
    """Retorna jobs PENDING antigos (> PENDING_JOB_REDISPATCH_AFTER) para redespacho."""
    result = await session.execute(
        select(GenerationJob)
        .where(GenerationJob.status == GenerationJobStatus.PENDING)
        .order_by(GenerationJob.updated_at.asc())
        .limit(limit)
    )
    return [
        job
        for job in result.scalars()
        if _is_recoverable_project_step_job(job) and pending_job_is_stale(job)
    ]


async def list_stale_running_jobs(session: AsyncSession, limit: int = 50) -> list[GenerationJob]:
    """Retorna jobs RUNNING abandonados (processo morreu no meio da etapa).

    Apos uma reinicializacao, nenhum outro processo esta executando esses jobs, entao
    redespacha-los e seguro em uma aplicacao de processo unico. Usa RUNNING_JOB_RECLAIM_AFTER
    (15 min) para evitar re-dispatchar jobs legítimos longos (steps de IA podem durar minutos).
    """
    result = await session.execute(
        select(GenerationJob)
        .where(GenerationJob.status == GenerationJobStatus.RUNNING)
        .order_by(GenerationJob.updated_at.asc())
        .limit(limit)
    )
    now = datetime.now(UTC)
    return [
        job
        for job in result.scalars()
        if _is_recoverable_project_step_job(job)
        and _job_stale_after_window(job, RUNNING_JOB_RECLAIM_AFTER, now)
    ]


def schedule_stale_job_recovery() -> None:
    """Redespacha jobs PENDING/RUNNING abandonados (aplicacao reiniciada no meio da etapa).

    Registrada como hook de startup do FastAPI; roda em background para nao bloquear o boot.
    Ignorada em APP_ENV=test para evitar interferencia com a suíte.
    """
    from app.config.settings import get_settings

    if get_settings().app_env.lower() == "test":
        return

    async def _recover() -> None:
        try:
            from app.database.session import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                pending = await list_stale_pending_jobs(session)
                running = await list_stale_running_jobs(session)
                jobs = [*pending, *running]
        except Exception as exc:
            logger.warning("startup_job_recovery_failed: %s", exc)
            return
        for job in jobs:
            try:
                dispatch_project_job(job.id)
            except Exception as exc:
                logger.warning("startup_job_redispatch_failed %s: %s", job.id, exc)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    asyncio.create_task(_recover(), name="startup-job-recovery")
