import asyncio
import logging
import socket
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select

from app.config.settings import Settings
from app.core.enums import GenerationJobStatus, GenerationJobType
from app.database.session import AsyncSessionLocal
from app.jobs.service import mark_job_failed, mark_job_running, mark_job_succeeded
from app.observability.redaction import redact_secrets
from app.observability.schemas import OperationalEventCreate
from app.observability.service import emit_project_event
from app.video_generation.models import GenerationJob
from app.workers.queue import QueueMessage, RedisJobQueue, redis_lock

logger = logging.getLogger(__name__)
JobHandler = Callable[[GenerationJob], Awaitable[dict[str, Any]]]


class MediaWorker:
    def __init__(
        self,
        redis: Redis,
        settings: Settings,
        handlers: dict[GenerationJobType, JobHandler],
        *,
        consumer: str | None = None,
    ) -> None:
        self.redis = redis
        self.settings = settings
        self.queue = RedisJobQueue(
            redis, stream=settings.worker_queue_name, group=settings.worker_consumer_group
        )
        self.handlers = handlers
        self.consumer = consumer or f"{socket.gethostname()}-{id(self):x}"
        self.stopping = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()
        self._last_started: dict[GenerationJobType, float] = {}
        self._limits = {
            GenerationJobType.VIDEO: asyncio.Semaphore(settings.worker_vibes_concurrency),
            GenerationJobType.IMAGE: asyncio.Semaphore(settings.worker_meta_image_concurrency),
            GenerationJobType.INGREDIENT: asyncio.Semaphore(1),
            GenerationJobType.QA: asyncio.Semaphore(settings.worker_meta_image_concurrency),
        }

    async def run(self) -> None:
        await self.queue.ensure_group()
        await self.recover_stale_database_jobs()
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        try:
            while not self.stopping.is_set():
                reclaimed = await self.queue.reclaim(
                    self.consumer, min_idle_ms=self.settings.worker_reclaim_seconds * 1000
                )
                message = reclaimed[0] if reclaimed else await self.queue.dequeue(self.consumer)
                if message:
                    task = asyncio.create_task(self.process(message))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
        finally:
            self.stopping.set()
            heartbeat.cancel()
            await asyncio.gather(heartbeat, *self._tasks, return_exceptions=True)

    async def recover_stale_database_jobs(self) -> int:
        """Recoloca jobs de mídia órfãos; PostgreSQL continua sendo a fonte de verdade."""
        cutoff = datetime.now(UTC) - timedelta(seconds=self.settings.worker_reclaim_seconds)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(GenerationJob).where(
                    GenerationJob.job_type.in_(self.handlers),
                    GenerationJob.status.in_(
                        {GenerationJobStatus.PENDING, GenerationJobStatus.RUNNING}
                    ),
                    GenerationJob.updated_at < cutoff,
                )
            )
            jobs = list(result.scalars())
            for job in jobs:
                if job.status == GenerationJobStatus.RUNNING:
                    job.status = GenerationJobStatus.PENDING
                    job.error = "Worker anterior perdeu o heartbeat; job recuperado."
                await self.queue.enqueue(job.id)
            if jobs:
                await session.commit()
            return len(jobs)

    async def process(self, message: QueueMessage) -> None:
        async with AsyncSessionLocal() as session:
            job = await session.get(GenerationJob, message.job_id)
            if job is None or job.status in {
                GenerationJobStatus.SUCCEEDED,
                GenerationJobStatus.CANCELLED,
            }:
                await self.queue.ack(message.message_id)
                return
            if job.attempts >= job.max_attempts:
                await mark_job_failed(session, job, error="Limite de tentativas atingido")
                await self.queue.ack(message.message_id)
                return
            handler = self.handlers.get(job.job_type)
            if handler is None:
                await mark_job_failed(session, job, error=f"Worker sem handler para {job.job_type}")
                await self.queue.ack(message.message_id)
                return
            limit = self._limits[job.job_type]
            try:
                async with AsyncExitStack() as stack:
                    await stack.enter_async_context(limit)
                    if job.job_type in {GenerationJobType.VIDEO, GenerationJobType.INGREDIENT}:
                        profile_key = (
                            f"{self.settings.worker_queue_name}:profile-lock:"
                            f"{self.settings.vibes_browser_profile_path.resolve()}"
                        )
                        acquired = await stack.enter_async_context(
                            redis_lock(self.redis, profile_key, ttl_seconds=3600)
                        )
                        if not acquired:
                            await self.queue.enqueue(job.id)
                            return
                    await self._respect_rate_limit(job.job_type)
                    await mark_job_running(session, job, "Worker iniciou tarefa de mídia.")
                    started_at = time.perf_counter()
                    await emit_project_event(
                        session,
                        OperationalEventCreate(
                            project_id=job.project_id,
                            job_id=job.id,
                            event_type="worker_job",
                            status="started",
                            provider=job.provider,
                            model=job.model,
                            operation=str(job.request_payload.get("operation") or job.job_type),
                            message="Worker iniciou tarefa de mídia.",
                            details={
                                "shot_id": job.request_payload.get("shot_id"),
                                "attempt": job.attempts,
                            },
                        ),
                    )
                    await session.commit()
                    response = await handler(job)
                    await session.refresh(job)
                    if job.status == GenerationJobStatus.CANCELLED:
                        logger.info("media_worker_job_cancelled job_id=%s", job.id)
                        return
                    external_id = str(response.get("external_job_id") or "").strip()
                    if external_id:
                        job.external_job_id = external_id
                    await mark_job_succeeded(session, job, response_payload=response)
                    await emit_project_event(
                        session,
                        OperationalEventCreate(
                            project_id=job.project_id,
                            job_id=job.id,
                            event_type="worker_job",
                            status="succeeded",
                            provider=job.provider,
                            model=job.model,
                            operation=str(job.request_payload.get("operation") or job.job_type),
                            message="Worker concluiu tarefa de mídia.",
                            details={
                                "shot_id": job.request_payload.get("shot_id"),
                                "duration_ms": round((time.perf_counter() - started_at) * 1000),
                            },
                        ),
                    )
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await session.rollback()
                await mark_job_failed(session, job, error=redact_secrets(exc))
                await emit_project_event(
                    session,
                    OperationalEventCreate(
                        project_id=job.project_id,
                        job_id=job.id,
                        event_type="worker_job",
                        status="failed",
                        provider=job.provider,
                        model=job.model,
                        operation=str(job.request_payload.get("operation") or job.job_type),
                        message=redact_secrets(exc),
                        details={
                            "shot_id": job.request_payload.get("shot_id"),
                            "error_class": type(exc).__name__,
                        },
                    ),
                )
                await session.commit()
                logger.warning(
                    "media_worker_job_failed job_id=%s error=%s",
                    job.id,
                    redact_secrets(exc),
                )
            finally:
                await self.queue.ack(message.message_id)

    async def _heartbeat_loop(self) -> None:
        while not self.stopping.is_set():
            await self.queue.heartbeat(self.consumer, self.settings.worker_heartbeat_seconds * 3)
            try:
                await asyncio.wait_for(
                    self.stopping.wait(), timeout=self.settings.worker_heartbeat_seconds
                )
            except TimeoutError:
                pass

    async def _respect_rate_limit(self, job_type: GenerationJobType) -> None:
        interval = float(self.settings.worker_rate_limit_seconds)
        if interval <= 0:
            return
        now = time.monotonic()
        wait = interval - (now - self._last_started.get(job_type, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_started[job_type] = time.monotonic()
