from celery import Celery

from app.config.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "storytelling",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="storytelling",
)
