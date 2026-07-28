from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import GenerationJobStatus
from app.jobs import service as jobs_service


def test_project_job_can_run_respects_exhausted_failed_status() -> None:
    exhausted = SimpleNamespace(
        status=GenerationJobStatus.FAILED,
        attempts=3,
        max_attempts=3,
    )
    retryable = SimpleNamespace(
        status=GenerationJobStatus.FAILED,
        attempts=2,
        max_attempts=3,
    )
    completed = SimpleNamespace(
        status=GenerationJobStatus.SUCCEEDED,
        attempts=1,
        max_attempts=3,
    )

    assert not jobs_service.project_job_can_run(cast(Any, exhausted))
    assert jobs_service.project_job_can_run(cast(Any, retryable))
    assert not jobs_service.project_job_can_run(cast(Any, completed))


@pytest.mark.asyncio
async def test_enqueue_project_step_does_not_dispatch_exhausted_failed_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = SimpleNamespace(
        status=GenerationJobStatus.FAILED,
        attempts=3,
        max_attempts=3,
    )
    dispatched: list[UUID] = []

    async def fake_create_or_resume_project_job(
        session: AsyncSession,
        project_id: UUID,
        step: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        _ = (session, project_id, step, payload)
        return job

    monkeypatch.setattr(
        jobs_service,
        "create_or_resume_project_job",
        fake_create_or_resume_project_job,
    )
    monkeypatch.setattr(jobs_service, "dispatch_project_job", dispatched.append)

    result = await jobs_service.enqueue_project_step(
        cast(AsyncSession, object()),
        uuid4(),
        "script",
    )

    assert result is job
    assert dispatched == []
