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
    _structured_json_content,
    analyze_with_ollama_cloud,
    conservative_qa_assessment,
    persist_qa_result,
    qa_correction_instruction,
)
from app.workers.handlers import default_handlers
from app.workers.main import main
from app.workers.queue import QueueMessage, RedisJobQueue, redis_lock


def test_structured_json_content_removes_markdown_fence() -> None:
    raw = '```json\n{"dimension_scores": {}, "reasons": [], "objective_failures": []}\n```'

    assert QAAssessment.model_validate_json(_structured_json_content(raw))


class FakeRedis:
    def __init__(self) -> None:
        self.stream: list[tuple[str, dict[str, str]]] = []
        self.values: dict[str, str] = {}
        self.acked: list[str] = []
        self.claims: list[dict[str, Any]] = []

    async def xgroup_create(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def xadd(self, stream: str, fields: dict[str, str], **_: Any) -> str:
        message_id = f"{len(self.stream) + 1}-0"
        self.stream.append((message_id, fields))
        return message_id

    async def xreadgroup(self, *args: Any, **kwargs: Any) -> Any:
        if not self.stream:
            return []
        return [(b"jobs", [self.stream.pop(0)])]

    async def xautoclaim(self, *args: Any, **kwargs: Any) -> Any:
        return ["0-0", list(self.stream), []]

    async def xclaim(self, *args: Any, **kwargs: Any) -> list[str]:
        self.claims.append(kwargs)
        return list(kwargs.get("message_ids") or [])

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

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def exists(self, key: str) -> int:
        return int(key in self.values)

    async def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)

    async def scan_iter(self, *, match: str) -> Any:
        prefix = match.removesuffix("*")
        for key in list(self.values):
            if key.startswith(prefix):
                yield key


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


async def test_redis_touch_renews_active_message_claim() -> None:
    redis = FakeRedis()
    queue = RedisJobQueue(redis, stream="jobs", group="workers")  # type: ignore[arg-type]

    await queue.touch("worker", "42-0")

    assert redis.claims == [
        {
            "min_idle_time": 0,
            "message_ids": ["42-0"],
            "idle": 0,
            "justid": True,
        }
    ]


async def test_worker_acknowledges_duplicate_message_for_active_job() -> None:
    from app.workers.worker import MediaWorker

    redis = FakeRedis()
    settings = Settings(_env_file=None)
    worker = MediaWorker(redis, settings, default_handlers(), consumer="current")  # type: ignore[arg-type]
    job_id = uuid4()
    worker._active_job_ids.add(job_id)

    await worker.process(QueueMessage(message_id="duplicate-1", job_id=job_id))

    assert redis.acked == ["duplicate-1"]
    # Renovar a posse não cria outra mensagem na fila.
    assert redis.stream == []


async def test_worker_requeues_profile_contention_after_releasing_job_ownership() -> None:
    from app.workers.worker import MediaWorker

    redis = FakeRedis()
    settings = Settings(_env_file=None)
    worker = MediaWorker(redis, settings, default_handlers(), consumer="current")  # type: ignore[arg-type]
    job_id = uuid4()
    job_lock_key = f"{settings.worker_queue_name}:job-lock:{job_id}"
    enqueue_state: list[tuple[bool, bool]] = []
    original_enqueue = worker.queue.enqueue

    async def profile_was_busy(message: QueueMessage, *, lost_event: Any = None) -> bool:
        assert message.job_id in worker._active_job_ids
        assert job_lock_key in redis.values
        return True

    async def observed_enqueue(requested_job_id: Any) -> str:
        enqueue_state.append(
            (requested_job_id in worker._active_job_ids, job_lock_key in redis.values)
        )
        return await original_enqueue(requested_job_id)

    worker._process_claimed_message = profile_was_busy  # type: ignore[method-assign]
    worker.queue.enqueue = observed_enqueue  # type: ignore[method-assign, assignment]

    await worker.process(QueueMessage(message_id="original", job_id=job_id))

    assert enqueue_state == [(False, False)]
    assert redis.stream == [("1-0", {"job_id": str(job_id)})]


def test_worker_serializes_images_that_share_the_meta_browser_profile() -> None:
    from app.workers.worker import MediaWorker

    redis = FakeRedis()
    settings = Settings(_env_file=None, worker_meta_image_concurrency=4)
    worker = MediaWorker(redis, settings, default_handlers())  # type: ignore[arg-type]

    assert worker._limits[GenerationJobType.IMAGE]._value == 1
    assert worker._limits[GenerationJobType.QA]._value == 4


async def test_browser_profile_lock_is_exclusive_and_token_safe() -> None:
    redis = FakeRedis()
    async with redis_lock(redis, "profile", ttl_seconds=60) as first:  # type: ignore[arg-type]
        assert first is True
        async with redis_lock(redis, "profile", ttl_seconds=60) as second:  # type: ignore[arg-type]
            assert second is False
    assert "profile" not in redis.values


async def test_worker_removes_only_stale_browser_profile_locks() -> None:
    from app.workers.worker import MediaWorker

    redis = FakeRedis()
    settings = Settings(_env_file=None)
    worker = MediaWorker(redis, settings, default_handlers(), consumer="current")  # type: ignore[arg-type]
    stale_key = (
        f"{settings.worker_queue_name}:profile-lock:{settings.meta_browser_profile_path.resolve()}"
    )
    active_key = (
        f"{settings.worker_queue_name}:profile-lock:{settings.vibes_browser_profile_path.resolve()}"
    )
    redis.values[stale_key] = "legacy-token"
    redis.values[active_key] = "other-worker:nonce"
    stale_job_key = f"{settings.worker_queue_name}:job-lock:{uuid4()}"
    redis.values[stale_job_key] = "dead-worker:nonce"
    redis.values[f"{settings.worker_queue_name}:heartbeat:other-worker"] = "alive"

    removed = await worker.clear_stale_profile_locks()

    assert removed == 2
    assert stale_key not in redis.values
    assert stale_job_key not in redis.values
    assert active_key in redis.values


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


def test_browser_profile_lock_ttl_is_shorter_for_images() -> None:
    from app.workers.worker import _profile_lock_ttl_seconds

    assert _profile_lock_ttl_seconds(GenerationJobType.IMAGE) == 300
    assert _profile_lock_ttl_seconds(GenerationJobType.VIDEO) == 2100


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


async def test_ollama_multimodal_qa_is_mockable(monkeypatch: Any, tmp_path: Any) -> None:
    import app.video_generation.qa as qa_module

    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg-placeholder")
    spec = SimpleNamespace(model_dump_json=lambda: '{"shot_id":"test"}')
    settings = SimpleNamespace(
        qa_ollama_multimodal_enabled=True,
        ollama_cloud_base_url="https://ollama.com/api",
        ollama_cloud_api_key="secret-value",
        ollama_cloud_vision_model="multimodal-model",
        qa_ollama_timeout_seconds=30,
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
            return json.dumps({"message": {"content": json.dumps(assessment)}}).encode()

    monkeypatch.setattr(qa_module.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    result = await analyze_with_ollama_cloud(spec, [frame])  # type: ignore[arg-type]
    assert result.dimension_scores["continuity"] == 90
    assert result.objective_failures == []


async def test_ollama_multimodal_qa_retries_invalid_response(
    monkeypatch: Any, tmp_path: Any
) -> None:
    import app.video_generation.qa as qa_module

    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg-placeholder")
    spec = SimpleNamespace(model_dump_json=lambda: '{"shot_id":"test"}')
    settings = SimpleNamespace(
        qa_ollama_multimodal_enabled=True,
        ollama_cloud_base_url="https://ollama.com/api",
        ollama_cloud_api_key="secret-value",
        ollama_cloud_vision_model="multimodal-model",
        qa_ollama_timeout_seconds=30,
    )
    monkeypatch.setattr(qa_module, "get_settings", lambda: settings)
    monkeypatch.setattr(qa_module, "ensure_provider_api_key", lambda *args: "secret-value")
    valid = {
        "dimension_scores": {name: 85 for name in qa_module.QA_DIMENSIONS},
        "reasons": [],
        "objective_failures": [],
    }
    responses = iter([qa_module.QAAssessment.model_json_schema(), valid])

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def read(self) -> bytes:
            content = json.dumps(next(responses))
            return json.dumps({"message": {"content": content}}).encode()

    monkeypatch.setattr(qa_module.urllib.request, "urlopen", lambda *args, **kwargs: Response())

    result = await analyze_with_ollama_cloud(spec, [frame])  # type: ignore[arg-type]

    assert result.dimension_scores["continuity"] == 85


async def test_ollama_multimodal_qa_falls_back_to_human_review(
    monkeypatch: Any, tmp_path: Any
) -> None:
    import app.video_generation.qa as qa_module

    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg-placeholder")
    spec = SimpleNamespace(model_dump_json=lambda: '{"shot_id":"test"}')
    settings = SimpleNamespace(
        qa_ollama_multimodal_enabled=True,
        ollama_cloud_base_url="https://ollama.com/api",
        ollama_cloud_api_key="secret-value",
        ollama_cloud_vision_model="multimodal-model",
        qa_ollama_timeout_seconds=30,
    )
    monkeypatch.setattr(qa_module, "get_settings", lambda: settings)
    monkeypatch.setattr(qa_module, "ensure_provider_api_key", lambda *args: "secret-value")

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def read(self) -> bytes:
            schema = json.dumps(qa_module.QAAssessment.model_json_schema())
            return json.dumps({"message": {"content": schema}}).encode()

    monkeypatch.setattr(qa_module.urllib.request, "urlopen", lambda *args, **kwargs: Response())

    result = await analyze_with_ollama_cloud(spec, [frame])  # type: ignore[arg-type]

    assert set(result.dimension_scores.values()) == {50}
    assert "duas tentativas" in result.reasons[0]
    assert result.objective_failures == []
