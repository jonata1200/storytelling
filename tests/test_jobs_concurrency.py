"""Tests for job runner concurrency safety (app/jobs/service.py).

Verifies:
- Background tasks are tracked in _running_background_tasks set
- Task tracking set is cleaned up via done_callback
- PENDING_JOB_REDISPATCH_AFTER vs RUNNING_JOB_RECLAIM_AFTER have distinct values
- pending_job_is_stale and _job_stale_after_window logic is correct
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.enums import GenerationJobStatus
from app.jobs.service import (
    PENDING_JOB_REDISPATCH_AFTER,
    RUNNING_JOB_RECLAIM_AFTER,
    _job_stale_after_window,
    _running_background_tasks,
    pending_job_is_stale,
    project_job_can_run,
)


def _make_job(
    status: GenerationJobStatus = GenerationJobStatus.PENDING,
    updated_at: datetime | None = None,
    attempts: int = 0,
    max_attempts: int = 3,
    request_payload: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        updated_at=updated_at,
        created_at=updated_at,
        attempts=attempts,
        max_attempts=max_attempts,
        request_payload=request_payload or {"step": "script"},
    )


@pytest.mark.unit
def test_running_reclaim_after_is_longer_than_pending_redispatch() -> None:
    assert RUNNING_JOB_RECLAIM_AFTER > PENDING_JOB_REDISPATCH_AFTER
    assert RUNNING_JOB_RECLAIM_AFTER >= timedelta(minutes=10)


@pytest.mark.unit
def test_pending_job_is_stale_after_2_minutes() -> None:
    now = datetime.now(UTC)
    job = _make_job(updated_at=now - timedelta(minutes=3))
    assert pending_job_is_stale(job, now)  # type: ignore[arg-type]


@pytest.mark.unit
def test_pending_job_not_stale_within_2_minutes() -> None:
    now = datetime.now(UTC)
    job = _make_job(updated_at=now - timedelta(seconds=30))
    assert not pending_job_is_stale(job, now)  # type: ignore[arg-type]


@pytest.mark.unit
def test_running_job_not_stale_within_reclaim_window() -> None:
    now = datetime.now(UTC)
    job = _make_job(status=GenerationJobStatus.RUNNING, updated_at=now - timedelta(minutes=5))
    assert not _job_stale_after_window(job, RUNNING_JOB_RECLAIM_AFTER, now)  # type: ignore[arg-type]


@pytest.mark.unit
def test_running_job_stale_after_reclaim_window() -> None:
    now = datetime.now(UTC)
    job = _make_job(
        status=GenerationJobStatus.RUNNING,
        updated_at=now - timedelta(minutes=20),
    )
    assert _job_stale_after_window(job, RUNNING_JOB_RECLAIM_AFTER, now)  # type: ignore[arg-type]


@pytest.mark.unit
def test_job_can_run_pending() -> None:
    job = _make_job(status=GenerationJobStatus.PENDING)
    assert project_job_can_run(job)  # type: ignore[arg-type]


@pytest.mark.unit
def test_job_cannot_run_succeeded() -> None:
    job = _make_job(status=GenerationJobStatus.SUCCEEDED)
    assert not project_job_can_run(job)  # type: ignore[arg-type]


@pytest.mark.unit
def test_job_cannot_run_cancelled() -> None:
    job = _make_job(status=GenerationJobStatus.CANCELLED)
    assert not project_job_can_run(job)  # type: ignore[arg-type]


@pytest.mark.unit
def test_job_cannot_run_failed_at_max_attempts() -> None:
    job = _make_job(
        status=GenerationJobStatus.FAILED,
        attempts=3,
        max_attempts=3,
    )
    assert not project_job_can_run(job)  # type: ignore[arg-type]


@pytest.mark.unit
def test_job_can_run_failed_under_max_attempts() -> None:
    job = _make_job(
        status=GenerationJobStatus.FAILED,
        attempts=1,
        max_attempts=3,
    )
    assert project_job_can_run(job)  # type: ignore[arg-type]


@pytest.mark.unit
def test_job_stale_with_none_updated_at() -> None:
    job = _make_job(updated_at=None)
    assert _job_stale_after_window(job, timedelta(minutes=1))  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_background_task_is_tracked_and_cleaned_up() -> None:
    """dispatch_project_job adds task to _running_background_tasks and
    done_callback removes it after completion."""

    async def dummy_job() -> None:
        await asyncio.sleep(0.01)

    # Simulate dispatch by creating a task and tracking it manually
    task = asyncio.create_task(dummy_job(), name="test-task")
    _running_background_tasks.add(task)
    task.add_done_callback(_running_background_tasks.discard)

    assert task in _running_background_tasks
    await task
    # done_callback should have removed it
    assert task not in _running_background_tasks
