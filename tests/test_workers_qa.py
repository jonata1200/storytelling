import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.config.settings import Settings
from app.core.enums import GenerationJobStatus, GenerationJobType
from app.jobs.service import project_job_can_run
from app.video_generation.models import GenerationJob
from app.video_generation.qa import (
    QAAssessment,
    analyze_with_meta,
    conservative_qa_assessment,
    persist_qa_result,
    qa_correction_instruction,
)
from app.workers.handlers import default_handlers
from app.workers.main import main
from app.workers.queue import RedisJobQueue, redis_lock


class FakeRedis:
    def __init__(self) -> None:
        self.stream: list[tuple[str, dict[str, str]]] = []
        self.values: dict[str, str] = {}
        self.acked: list[str] = []

    async def xgroup_create(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        message_id = f"{len(self.stream) + 1}-0"
        self.stream.append((message_id, fields))
        return message_id

    async def xreadgroup(self, *args: Any, **kwargs: Any) -> Any:
        if not self.stream:
            return []
        return [(b"jobs", [self.stream.pop(0)])]

    async def xautoclaim(self, *args: Any, **kwargs: Any) -> Any:
        return ["0-0", list(self.stream), []]

    async def xack(self, stream: str, group: str, message_id: str) -> None:
        self.acked.append(message_id)

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, count: int, key: str, token: str) -> int:
        if self.values.get(key) == token:
            del self.values[key]
            return 1
        return 0


async def test_redis_enqueue_dequeue_and_reclaim() -> None:
    redis = FakeRedis()
    queue = RedisJobQueue(redis, stream="jobs", group="workers")  # type: ignore[arg-type]
    job_id = uuid4()
    message_id = await queue.enqueue(job_id)
    assert message_id == "1-0"
    reclaimed = await queue.reclaim("worker", min_idle_ms=100)
    assert reclaimed[0].job_id == job_id
    message = await queue.dequeue("worker")
    assert message is not None and message.job_id == job_id
    await queue.ack(message.message_id)
    assert redis.acked == ["1-0"]


async def test_browser_profile_lock_is_exclusive_and_token_safe() -> None:
    redis = FakeRedis()
    async with redis_lock(redis, "profile", ttl_seconds=60) as first:  # type: ignore[arg-type]
        assert first is True
        async with redis_lock(redis, "profile", ttl_seconds=60) as second:  # type: ignore[arg-type]
            assert second is False
    assert "profile" not in redis.values


async def test_qa_scores_are_bounded_and_uncertain_goes_to_human_review() -> None:
    class Session:
        def __init__(self) -> None:
            self.added: list[Any] = []

        def add(self, value: Any) -> None:
            self.added.append(value)

        async def flush(self) -> None:
            return None

    session = Session()
    result = await persist_qa_result(
        session,  # type: ignore[arg-type]
        project_id=uuid4(),
        shot_id=uuid4(),
        segment_id=uuid4(),
        generation_job_id=uuid4(),
        assessment=QAAssessment(
            dimension_scores={
                "characters": 110,
                "location": 80,
                "character_state": 60,
                "critical_prop": 40,
                "primary_action": 70,
                "continuity": -1,
            },
            reasons=["objeto mudou de mão"],
        ),
        compiler_version="vibes_shot_v1",
    )
    assert result.total_score == 58
    assert result.needs_human_review is True
    assert result.decision == "review"
    assert "critical_prop" in qa_correction_instruction(result)


def test_retry_policy_stops_at_max_attempts() -> None:
    job = GenerationJob(
        project_id=uuid4(),
        job_type=GenerationJobType.VIDEO,
        status=GenerationJobStatus.FAILED,
        progress=50,
        attempts=2,
        max_attempts=2,
        provider="vibes",
        model="vibes",
        idempotency_key="key",
        request_payload={},
        response_payload={},
    )
    assert project_job_can_run(job) is False


def test_pending_and_running_job_recovery_windows() -> None:
    from app.jobs.service import _job_stale_after_window, pending_job_is_stale

    now = datetime.now(UTC)
    job = SimpleNamespace(
        status=GenerationJobStatus.PENDING,
        updated_at=now - timedelta(minutes=3),
        created_at=now - timedelta(minutes=3),
    )
    assert pending_job_is_stale(job, now) is True  # type: ignore[arg-type]
    job.status = GenerationJobStatus.RUNNING
    assert _job_stale_after_window(job, timedelta(minutes=2), now) is True  # type: ignore[arg-type]


def test_worker_command_is_exposed() -> None:
    assert callable(main)
    settings = Settings(_env_file=None)
    assert settings.worker_vibes_concurrency == 1


def test_all_media_job_types_have_worker_handlers() -> None:
    assert set(default_handlers()) == {
        GenerationJobType.IMAGE,
        GenerationJobType.VIDEO,
        GenerationJobType.INGREDIENT,
        GenerationJobType.QA,
    }


def test_conservative_qa_never_auto_rejects() -> None:
    result = conservative_qa_assessment(SimpleNamespace())  # type: ignore[arg-type]
    assert set(result.dimension_scores.values()) == {50}
    assert result.objective_failures == []


def test_settings_bound_rate_limits_and_auto_regeneration() -> None:
    settings = Settings(
        _env_file=None,
        worker_rate_limit_seconds=1.5,
        shot_auto_regeneration_max_attempts=3,
    )
    assert settings.worker_rate_limit_seconds == 1.5
    assert settings.shot_auto_regeneration_enabled is True
    assert settings.shot_auto_regeneration_max_attempts == 3


async def test_meta_multimodal_qa_is_mockable(monkeypatch: Any, tmp_path: Any) -> None:
    import app.video_generation.qa as qa_module

    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg-placeholder")
    spec = SimpleNamespace(model_dump_json=lambda: '{"shot_id":"test"}')
    settings = SimpleNamespace(
        qa_meta_multimodal_enabled=True,
        meta_base_url="https://meta.example/v1",
        meta_api_key="secret-value",
        meta_default_model="multimodal-model",
        qa_meta_timeout_seconds=30,
    )
    monkeypatch.setattr(qa_module, "get_settings", lambda: settings)
    monkeypatch.setattr(qa_module, "ensure_provider_api_key", lambda *args: "secret-value")

    assessment = {
        "dimension_scores": {name: 90 for name in qa_module.QA_DIMENSIONS},
        "reasons": ["coerente"],
        "objective_failures": [],
    }

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(assessment)}}]}
            ).encode()

    monkeypatch.setattr(qa_module.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    result = await analyze_with_meta(spec, [frame])  # type: ignore[arg-type]
    assert result.dimension_scores["continuity"] == 90
    assert result.objective_failures == []
