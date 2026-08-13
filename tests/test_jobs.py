import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import GenerationJobStatus
from app.jobs import runner as jobs_runner
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


def test_scenes_is_a_valid_project_step() -> None:
    assert jobs_service.normalize_step("scenes") == "scenes"
    assert "scenes" in jobs_service.PROJECT_STEP_JOB_TYPES


def test_pending_job_is_not_stale_when_recent() -> None:
    now = datetime.now(UTC)
    job = SimpleNamespace(
        status=GenerationJobStatus.PENDING,
        updated_at=now - timedelta(seconds=15),
        created_at=now - timedelta(seconds=15),
    )

    assert jobs_service.pending_job_is_stale(cast(Any, job), now) is False


def test_pending_job_is_stale_after_redispatch_window() -> None:
    now = datetime.now(UTC)
    job = SimpleNamespace(
        status=GenerationJobStatus.PENDING,
        updated_at=now - timedelta(minutes=3),
        created_at=now - timedelta(minutes=3),
    )

    assert jobs_service.pending_job_is_stale(cast(Any, job), now) is True


def test_schedule_stale_job_recovery_is_noop_without_running_loop() -> None:
    # Fora de um loop assíncrono (ex.: import inicial), a recuperação não deve levantar.
    jobs_service.schedule_stale_job_recovery()


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
        return jobs_service.JobEnqueueDecision(job=cast(Any, job), should_dispatch=False)

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


@pytest.mark.asyncio
async def test_run_video_raises_when_all_clip_jobs_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    failed_job = SimpleNamespace(
        status=GenerationJobStatus.FAILED,
        error="Google AI Videos submit HTTP 400: Unsupported video generation request",
    )

    async def fake_generate_video_clips(*args: Any, **kwargs: Any) -> tuple[list[Any], list[Any]]:
        _ = (args, kwargs)
        return [failed_job], []

    monkeypatch.setattr(jobs_runner, "generate_video_clips", fake_generate_video_clips)

    with pytest.raises(RuntimeError, match="Unsupported video generation request"):
        await jobs_runner._run_video(cast(AsyncSession, object()), project_id, {})


@pytest.mark.asyncio
async def test_script_job_only_generates_script(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    idea_id = uuid4()
    script_id = uuid4()
    calls: list[str] = []

    async def fake_latest(
        session: AsyncSession, model: type[Any], requested_project_id: UUID
    ) -> Any:
        _ = session, model
        assert requested_project_id == project_id
        return SimpleNamespace(id=idea_id)

    async def fake_generate_story_ideas(*args: Any, **kwargs: Any) -> list[Any]:
        calls.append("ideas")
        return []

    async def fake_generate_script(*args: Any, **kwargs: Any) -> Any:
        calls.append("script")
        assert args[1] == project_id
        assert args[2] == idea_id
        return SimpleNamespace(id=script_id)

    async def fake_generate_scenes_and_shots(*args: Any, **kwargs: Any) -> list[Any]:
        calls.append("scenes")
        return []

    monkeypatch.setattr(jobs_runner, "_latest", fake_latest)
    monkeypatch.setattr(jobs_runner, "generate_story_ideas", fake_generate_story_ideas)
    monkeypatch.setattr(jobs_runner, "generate_script", fake_generate_script)
    monkeypatch.setattr(
        jobs_runner,
        "generate_scenes_and_shots",
        fake_generate_scenes_and_shots,
    )

    result = await jobs_runner._run_script(cast(AsyncSession, object()), project_id)

    assert result == {"script_id": str(script_id)}
    assert calls == ["script"]


@pytest.mark.asyncio
async def test_scenes_job_uses_latest_script(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    script_id = uuid4()
    calls: list[str] = []

    async def fake_latest(
        session: AsyncSession, model: type[Any], requested_project_id: UUID
    ) -> Any:
        _ = session, model
        assert requested_project_id == project_id
        return SimpleNamespace(id=script_id)

    async def fake_generate_scenes_and_shots(*args: Any, **kwargs: Any) -> list[Any]:
        calls.append("scenes")
        assert args[1] == project_id
        assert args[2] == script_id
        return [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]

    monkeypatch.setattr(jobs_runner, "_latest", fake_latest)
    monkeypatch.setattr(
        jobs_runner,
        "generate_scenes_and_shots",
        fake_generate_scenes_and_shots,
    )

    result = await jobs_runner._run_scenes(cast(AsyncSession, object()), project_id)

    assert result == {"script_id": str(script_id), "scene_count": 2}
    assert calls == ["scenes"]


@pytest.mark.asyncio
async def test_set_project_job_action_dedupes_identical_consecutive_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(metadata_json={})
    fetched: list[UUID] = []

    async def fake_get_or_create(session: Any, project_id: UUID) -> Any:
        fetched.append(project_id)
        return settings

    monkeypatch.setattr(
        jobs_service,
        "get_or_create_production_settings",
        fake_get_or_create,
    )

    class _FlushSession:
        def __init__(self) -> None:
            self.flushes = 0

        async def flush(self) -> None:
            self.flushes += 1

    flush_session = _FlushSession()
    session = cast(AsyncSession, flush_session)
    job = cast(
        Any,
        SimpleNamespace(
            id=uuid4(),
            project_id=uuid4(),
            request_payload={"step": "script"},
        ),
    )

    await jobs_service._set_project_job_action(
        session,
        job,
        status="running",
        message="Executando script.",
    )
    first_updated_at = settings.metadata_json["ai_action"]["updated_at"]
    await jobs_service._set_project_job_action(
        session,
        job,
        status="running",
        message="Executando script.",
    )

    action = settings.metadata_json["ai_action"]
    assert len(action["events"]) == 1  # evento identico nao duplica o historico
    assert len(fetched) == 1  # settings buscadas apenas uma vez por execução
    assert action["updated_at"] >= first_updated_at  # updated_at mantido fresco

    await jobs_service._set_project_job_action(
        session,
        job,
        status="running",
        message="Novo progresso.",
    )
    assert len(settings.metadata_json["ai_action"]["events"]) == 2


class _FakeStaleJobSession:
    """Sessão falsa que devolve uma lista fixa de jobs (simula o filtro SQL)."""

    def __init__(self, jobs: list[Any]) -> None:
        self.jobs = jobs

    async def execute(self, statement: object) -> "_FakeStaleJobResult":
        _ = statement
        return _FakeStaleJobResult(self.jobs)


class _FakeStaleJobResult:
    def __init__(self, jobs: list[Any]) -> None:
        self.jobs = jobs

    def scalars(self) -> list[Any]:
        return self.jobs


@pytest.mark.asyncio
async def test_list_stale_pending_jobs_returns_only_stale_pending_jobs() -> None:
    now = datetime.now(UTC)
    stale = SimpleNamespace(
        status=GenerationJobStatus.PENDING,
        updated_at=now - timedelta(minutes=3),
        created_at=now - timedelta(minutes=3),
        request_payload={"step": "video", "payload": {}},
    )
    fresh = SimpleNamespace(
        status=GenerationJobStatus.PENDING,
        updated_at=now - timedelta(seconds=15),
        created_at=now - timedelta(seconds=15),
        request_payload={"step": "video", "payload": {}},
    )
    clip_job = SimpleNamespace(
        status=GenerationJobStatus.PENDING,
        updated_at=now - timedelta(minutes=3),
        created_at=now - timedelta(minutes=3),
        request_payload={"storyboard_frame_id": str(uuid4())},
    )
    session = _FakeStaleJobSession([stale, fresh, clip_job])

    result = await jobs_service.list_stale_pending_jobs(cast(AsyncSession, session))

    assert result == [stale]


@pytest.mark.asyncio
async def test_list_stale_running_jobs_returns_abandoned_running_jobs() -> None:
    now = datetime.now(UTC)
    stale = SimpleNamespace(
        status=GenerationJobStatus.RUNNING,
        updated_at=now - timedelta(minutes=3),
        created_at=now - timedelta(minutes=3),
        request_payload={"step": "video", "payload": {}},
    )
    fresh = SimpleNamespace(
        status=GenerationJobStatus.RUNNING,
        updated_at=now - timedelta(seconds=15),
        created_at=now - timedelta(seconds=15),
        request_payload={"step": "video", "payload": {}},
    )
    clip_job = SimpleNamespace(
        status=GenerationJobStatus.RUNNING,
        updated_at=now - timedelta(minutes=3),
        created_at=now - timedelta(minutes=3),
        request_payload={"storyboard_frame_id": str(uuid4())},
    )
    session = _FakeStaleJobSession([stale, fresh, clip_job])

    result = await jobs_service.list_stale_running_jobs(cast(AsyncSession, session))

    assert result == [stale]


@pytest.mark.asyncio
async def test_schedule_stale_job_recovery_redispatchs_stale_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_pending = SimpleNamespace(id=uuid4())
    stale_running = SimpleNamespace(id=uuid4())

    async def fake_list_stale_pending_jobs(
        session: object, limit: int = 50
    ) -> list[Any]:
        _ = (session, limit)
        return [stale_pending]

    async def fake_list_stale_running_jobs(
        session: object, limit: int = 50
    ) -> list[Any]:
        _ = (session, limit)
        return [stale_running]

    dispatched: list[UUID] = []

    class _FakeRecoverySession:
        def __init__(self) -> None:
            self._session = object()

        async def __aenter__(self) -> Any:
            return self._session

        async def __aexit__(self, *args: Any) -> None:
            _ = args

    monkeypatch.setattr(
        jobs_service, "list_stale_pending_jobs", fake_list_stale_pending_jobs
    )
    monkeypatch.setattr(
        jobs_service, "list_stale_running_jobs", fake_list_stale_running_jobs
    )
    monkeypatch.setattr(jobs_service, "dispatch_project_job", dispatched.append)
    monkeypatch.setattr(
        "app.database.session.AsyncSessionLocal",
        _FakeRecoverySession,
    )
    monkeypatch.setattr(
        "app.config.settings.get_settings",
        lambda: SimpleNamespace(app_env="local"),
    )

    jobs_service.schedule_stale_job_recovery()
    await asyncio.sleep(0.05)

    assert dispatched == [stale_pending.id, stale_running.id]
