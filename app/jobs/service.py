import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from celery.exceptions import CeleryError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import GenerationJobStatus, GenerationJobType
from app.production.service import get_or_create_production_settings
from app.projects.repository import ProjectRepository
from app.video_generation.models import GenerationJob

PROJECT_STEP_JOB_TYPES = {
    "initial_script": GenerationJobType.ANALYSIS,
    "ideas": GenerationJobType.ANALYSIS,
    "script": GenerationJobType.ANALYSIS,
    "visual": GenerationJobType.IMAGE,
    "storyboard": GenerationJobType.IMAGE,
    "video": GenerationJobType.VIDEO,
    "finalization": GenerationJobType.RENDER,
    "quality": GenerationJobType.ANALYSIS,
}

TERMINAL_JOB_STATUSES = {
    GenerationJobStatus.SUCCEEDED,
    GenerationJobStatus.CANCELLED,
}


def normalize_step(value: str) -> str:
    step = str(value or "").strip().lower().replace("-", "_")
    if step not in PROJECT_STEP_JOB_TYPES:
        allowed = ", ".join(sorted(PROJECT_STEP_JOB_TYPES))
        raise ValueError(f"Etapa de job invalida: {step or '<vazia>'}. Use: {allowed}.")
    return step


def job_idempotency_key(project_id: UUID, step: str, payload: dict) -> str:
    body = {
        "project_id": str(project_id),
        "step": normalize_step(step),
        "payload": payload,
    }
    serialized = json.dumps(body, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def _set_project_job_action(
    session: AsyncSession,
    job: GenerationJob,
    *,
    status: str,
    message: str,
    error: str | None = None,
) -> None:
    settings = await get_or_create_production_settings(session, job.project_id)
    metadata = dict(settings.metadata_json or {})
    action = str(job.request_payload.get("step") or "project_step")
    previous_action = metadata.get("ai_action")
    previous_events = (
        previous_action.get("events", []) if isinstance(previous_action, dict) else []
    )
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
) -> GenerationJob:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        raise ValueError("Projeto nao encontrado.")
    normalized_step = normalize_step(step)
    clean_payload = dict(payload or {})
    request_payload = {"step": normalized_step, "payload": clean_payload}
    idempotency_key = job_idempotency_key(project_id, normalized_step, clean_payload)
    result = await session.execute(
        select(GenerationJob).where(GenerationJob.idempotency_key == idempotency_key)
    )
    job = result.scalars().first()
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
        await session.flush()
    elif job.status == GenerationJobStatus.FAILED and job.attempts < job.max_attempts:
        job.status = GenerationJobStatus.PENDING
        job.progress = 0
        job.error = None
        job.completed_at = None
        job.response_payload = {}
        await session.flush()
    await _set_project_job_action(
        session,
        job,
        status="queued" if job.status != GenerationJobStatus.SUCCEEDED else "completed",
        message=(
            "Etapa enfileirada para execucao pelo worker."
            if job.status != GenerationJobStatus.SUCCEEDED
            else "Etapa ja concluida anteriormente."
        ),
    )
    await session.commit()
    await session.refresh(job)
    return job


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


def dispatch_project_job(job_id: UUID) -> None:
    from app.workers.tasks import run_project_step

    try:
        run_project_step.delay(str(job_id))
    except CeleryError as exc:
        raise RuntimeError(f"Nao foi possivel enfileirar job no Celery: {exc}") from exc


async def enqueue_project_step(
    session: AsyncSession,
    project_id: UUID,
    step: str,
    payload: dict | None = None,
    *,
    dispatch: bool = True,
) -> GenerationJob:
    job = await create_or_resume_project_job(session, project_id, step, payload)
    if dispatch and job.status not in TERMINAL_JOB_STATUSES:
        dispatch_project_job(job.id)
    return job
