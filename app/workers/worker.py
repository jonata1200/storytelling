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

from app.config.settings import Settings, get_settings
from app.core.enums import GenerationJobStatus, GenerationJobType
from app.database.session import get_worker_sessionmaker
from app.jobs.service import mark_job_failed, mark_job_running, mark_job_succeeded
from app.observability.redaction import redact_secrets
from app.observability.schemas import OperationalEventCreate
from app.observability.service import emit_project_event
from app.video_generation.models import GenerationJob
from app.workers.queue import QueueMessage, RedisJobQueue, redis_lock

logger = logging.getLogger(__name__)
JobHandler = Callable[[GenerationJob], Awaitable[dict[str, Any]]]
PROFILE_LOCK_RETRY_SECONDS = 2.0


def _profile_lock_ttl_seconds(job_type: GenerationJobType) -> int:
    return 300 if job_type == GenerationJobType.IMAGE else 2100


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
        # ARQ-01.4: o worker usa pool de conexões dedicado (menor), em vez de
        # competir pelo pool da aplicação web.
        self.sessionmaker = get_worker_sessionmaker()
        self.stopping = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()
        self._active_job_ids: set[Any] = set()
        self._last_started: dict[GenerationJobType, float] = {}
        self._limits = {
            GenerationJobType.VIDEO: asyncio.Semaphore(settings.worker_vibes_concurrency),
            # Todas as imagens Meta compartilham um único perfil de navegador. Executá-las
            # em paralelo apenas cria contenção no mesmo perfil e não aumenta a vazão.
            GenerationJobType.IMAGE: asyncio.Semaphore(1),
            GenerationJobType.INGREDIENT: asyncio.Semaphore(1),
            GenerationJobType.QA: asyncio.Semaphore(settings.worker_meta_image_concurrency),
        }

    async def run(self) -> None:
        await self.queue.ensure_group()
        await self.clear_stale_profile_locks()
        await self.recover_stale_database_jobs()
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        recovery = asyncio.create_task(self._database_recovery_loop())
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
            recovery.cancel()
            await asyncio.gather(heartbeat, recovery, *self._tasks, return_exceptions=True)

    async def clear_stale_profile_locks(self) -> int:
        """Remove locks de perfil/job deixados por workers mortos."""

        removed = 0
        profile_paths = {
            self.settings.meta_browser_profile_path.resolve(),
            self.settings.vibes_browser_profile_path.resolve(),
        }
        lock_keys = {
            f"{self.settings.worker_queue_name}:profile-lock:{profile_path}"
            for profile_path in profile_paths
        }
        async for raw_key in self.redis.scan_iter(
            match=f"{self.settings.worker_queue_name}:job-lock:*"
        ):
            lock_keys.add(raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key))
        for key in lock_keys:
            raw_token = await self.redis.get(key)
            if raw_token is None:
                continue
            token = raw_token.decode() if isinstance(raw_token, bytes) else str(raw_token)
            owner, separator, _nonce = token.rpartition(":")
            heartbeat_exists = bool(
                separator
                and owner
                and await self.redis.exists(f"{self.settings.worker_queue_name}:heartbeat:{owner}")
            )
            if not heartbeat_exists:
                removed += int(await self.redis.delete(key))
        return removed

    async def recover_stale_database_jobs(self) -> int:
        """Recoloca jobs de mídia órfãos; PostgreSQL continua sendo a fonte de verdade."""
        cutoff = datetime.now(UTC) - timedelta(seconds=self.settings.worker_reclaim_seconds)
        async with self.sessionmaker() as session:
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
            recovered = 0
            for job in jobs:
                job_lock_key = f"{self.settings.worker_queue_name}:job-lock:{job.id}"
                if await self.redis.exists(job_lock_key):
                    continue
                # Claim atômico por job_id para impedir que múltiplos workers (ou o
                # startup + o loop periódico) enfileirem o mesmo job simultaneamente.
                recovery_key = f"{self.settings.worker_queue_name}:recovery-lock:{job.id}"
                claimed = await self.redis.set(
                    recovery_key,
                    self.consumer,
                    nx=True,
                    ex=max(30, self.settings.worker_reclaim_seconds),
                )
                if not claimed:
                    continue
                if job.status == GenerationJobStatus.RUNNING:
                    job.status = GenerationJobStatus.PENDING
                    job.error = "Worker anterior perdeu o heartbeat; job recuperado."
                await self.queue.enqueue(job.id)
                recovered += 1
            if recovered:
                await session.commit()
            return recovered

    async def process(self, message: QueueMessage) -> None:
        """Executa uma mensagem uma única vez e mantém sua posse durante jobs longos."""
        # ARQ-05: contrato "preferência de runtime ⇒ cache_clear no handler"
        # centralizado em UM ponto. Toda preferência gravada pela UI é re-ler
        # aqui, antes de qualquer handler rodar — cobre IMAGE/VIDEO/QA/
        # INGREDIENT sem que cada handler precise lembrar de limpar o cache.
        get_settings.cache_clear()
        if message.job_id in self._active_job_ids:
            logger.info("media_worker_duplicate_ignored job_id=%s", message.job_id)
            # A mensagem original continua protegida pelo heartbeat da tarefa ativa.
            # Esta é apenas uma entrada duplicada do mesmo job e pode ser confirmada.
            await self.queue.ack(message.message_id)
            return
        job_lock_key = f"{self.settings.worker_queue_name}:job-lock:{message.job_id}"
        requeue_after_release = False
        lost_event = asyncio.Event()
        async with redis_lock(
            self.redis,
            job_lock_key,
            ttl_seconds=max(60, self.settings.worker_reclaim_seconds * 2),
            owner=self.consumer,
            renew_interval_seconds=max(10.0, self.settings.worker_reclaim_seconds / 2),
            lost_event=lost_event,
        ) as acquired:
            if not acquired:
                logger.info("media_worker_job_lock_busy job_id=%s", message.job_id)
                return
            self._active_job_ids.add(message.job_id)
            heartbeat = asyncio.create_task(self._message_heartbeat_loop(message))
            try:
                requeue_after_release = await self._process_claimed_message(
                    message, lost_event=lost_event
                )
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                self._active_job_ids.discard(message.job_id)
        if requeue_after_release:
            # Só publique a nova mensagem depois de liberar as marcações de atividade e
            # o lock do job. Caso contrário, ela pode ser consumida e descartada como
            # duplicata antes que esta execução termine.
            await self.queue.enqueue(message.job_id)

    async def _process_claimed_message(
        self, message: QueueMessage, *, lost_event: asyncio.Event | None = None
    ) -> bool:
        async with self.sessionmaker() as session:
            job = await session.get(GenerationJob, message.job_id)
            if job is None or job.status in {
                GenerationJobStatus.SUCCEEDED,
                GenerationJobStatus.CANCELLED,
            }:
                await self.queue.ack(message.message_id)
                return False
            if job.attempts >= job.max_attempts:
                await mark_job_failed(session, job, error="Limite de tentativas atingido")
                await self.queue.ack(message.message_id)
                return False
            handler = self.handlers.get(job.job_type)
            if handler is None:
                await mark_job_failed(session, job, error=f"Worker sem handler para {job.job_type}")
                await self.queue.ack(message.message_id)
                return False
            limit = self._limits[job.job_type]
            try:
                async with AsyncExitStack() as stack:
                    await stack.enter_async_context(limit)
                    if job.job_type in {
                        GenerationJobType.IMAGE,
                        GenerationJobType.VIDEO,
                        GenerationJobType.INGREDIENT,
                    }:
                        profile_path = (
                            self.settings.meta_browser_profile_path
                            if job.job_type == GenerationJobType.IMAGE
                            else self.settings.vibes_browser_profile_path
                        )
                        profile_key = (
                            f"{self.settings.worker_queue_name}:profile-lock:"
                            f"{profile_path.resolve()}"
                        )
                        acquired = await stack.enter_async_context(
                            redis_lock(
                                self.redis,
                                profile_key,
                                ttl_seconds=_profile_lock_ttl_seconds(job.job_type),
                                owner=self.consumer,
                                # Renova o TTL durante o job: lote de vídeo (30 min
                                # de poll) + QA pode exceder o TTL estático de
                                # 2100s e liberaria o perfil para outro job.
                                renew_interval_seconds=max(
                                    10.0, self.settings.worker_reclaim_seconds / 2
                                ),
                                lost_event=lost_event,
                            )
                        )
                        if not acquired:
                            # Evita um loop quente que cria milhares de mensagens enquanto
                            # outro job ou um lock órfão ainda ocupa o perfil do navegador.
                            await asyncio.sleep(PROFILE_LOCK_RETRY_SECONDS)
                            return True
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
                    if lost_event is not None and lost_event.is_set():
                        # O lock do job foi perdido durante o processamento: outro worker
                        # pode ter assumido o mesmo job. Aborta sem marcar sucesso para
                        # evitar dupla execução/duplo custo.
                        logger.warning(
                            "media_worker_job_lock_lost job_id=%s", job.id
                        )
                        await session.rollback()
                        return False
                    await session.refresh(job)
                    if job.status == GenerationJobStatus.CANCELLED:
                        logger.info("media_worker_job_cancelled job_id=%s", job.id)
                        return False
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
        return False

    async def _message_heartbeat_loop(self, message: QueueMessage) -> None:
        interval = max(10.0, min(30.0, self.settings.worker_reclaim_seconds / 3))
        # Primeiro touch imediato: elimina a janela inicial em que a mensagem
        # fica idle e pode ser reivindicada por outro worker antes do heartbeat.
        await self._touch_message(message)
        while not self.stopping.is_set():
            await asyncio.sleep(interval)
            await self._touch_message(message)

    async def _touch_message(self, message: QueueMessage) -> None:
        try:
            owned = await self.queue.touch(self.consumer, message.message_id)
            if not owned:
                logger.warning(
                    "media_worker_message_ownership_lost job_id=%s message_id=%s",
                    message.job_id,
                    message.message_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "media_worker_message_heartbeat_failed job_id=%s message_id=%s",
                message.job_id,
                message.message_id,
            )

    async def _heartbeat_loop(self) -> None:
        while not self.stopping.is_set():
            await self.queue.heartbeat(self.consumer, self.settings.worker_heartbeat_seconds * 3)
            try:
                await asyncio.wait_for(
                    self.stopping.wait(), timeout=self.settings.worker_heartbeat_seconds
                )
            except TimeoutError:
                pass

    async def _database_recovery_loop(self) -> None:
        """Reenfileira periodicamente jobs órfãos sem exigir reinício do worker."""
        interval = max(30, self.settings.worker_reclaim_seconds)
        while not self.stopping.is_set():
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=interval)
            except TimeoutError:
                try:
                    await self.recover_stale_database_jobs()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("media_worker_database_recovery_failed")

    async def _respect_rate_limit(self, job_type: GenerationJobType) -> None:
        interval = float(self.settings.worker_rate_limit_seconds)
        if interval <= 0:
            return
        now = time.monotonic()
        wait = interval - (now - self._last_started.get(job_type, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_started[job_type] = time.monotonic()
