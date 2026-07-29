import asyncio
from uuid import UUID

from celery.utils.log import get_task_logger

from app.database.session import engine
from app.jobs.runner import run_project_step_job
from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


async def _run_project_step_with_fresh_pool(job_id: UUID) -> dict:
    await engine.dispose()
    try:
        return await run_project_step_job(job_id)
    finally:
        await engine.dispose()


@celery_app.task(name="app.workers.tasks.ping")
def ping() -> str:
    return "pong"


@celery_app.task(
    bind=True,
    name="app.workers.tasks.run_project_step",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_project_step(self: object, job_id: str) -> dict:
    _ = self
    logger.info("Running project step job %s", job_id)
    return asyncio.run(_run_project_step_with_fresh_pool(UUID(job_id)))
