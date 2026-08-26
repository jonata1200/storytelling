"""Testes do provider de vídeo OpenRouter e da geração de vídeo dos segmentos."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AssetKind, GenerationJobStatus
from app.providers.video import openrouter as openrouter_module
from app.providers.video.openrouter import OpenRouterVideoProvider
from app.providers.video.types import (
    VideoGenerationRequest,
    VideoImageInput,
    VideoJob,
)
from app.video_generation import (
    continuous,
    continuous_generation,
    continuous_review,
)
from app.video_generation.continuous_review import (
    generate_continuous_video_segments,
)
from app.video_generation.models import ContinuousVideoSegment


def _video_request(output_dir: Path | None = None) -> VideoGenerationRequest:
    from app.config.settings import get_settings

    resolved_output = output_dir or (
        Path(get_settings().local_storage_path) / "test_openrouter_videos"
    )
    return VideoGenerationRequest(
        model="bytedance/seedance-2.0-mini",
        prompt="Clara entra no observatorio e encontra o relogio.",
        duration=8,
        aspect_ratio="9:16",
        resolution="720p",
        generate_audio=True,
        seed=42,
        frame_images=[
            VideoImageInput(url="data:image/jpeg;base64,Zmlyc3Q=", frame_type="first_frame"),
            VideoImageInput(url="data:image/jpeg;base64,bGFzdA==", frame_type="last_frame"),
        ],
        input_references=[
            VideoImageInput(url="data:image/jpeg;base64,cmVm"),
        ],
        output_dir=resolved_output,
    )


def test_openrouter_request_body_includes_frames_references_and_options() -> None:
    provider = OpenRouterVideoProvider()
    body = provider._request_body(_video_request())

    assert body["model"] == "bytedance/seedance-2.0-mini"
    assert body["duration"] == 8
    assert body["aspect_ratio"] == "9:16"
    assert body["resolution"] == "720p"
    assert body["generate_audio"] is True
    assert body["seed"] == 42
    assert body["frame_images"] == [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,Zmlyc3Q="},
            "frame_type": "first_frame",
        },
        {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,bGFzdA=="},
            "frame_type": "last_frame",
        },
    ]
    assert body["input_references"] == [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,cmVm"}}
    ]


class _FakeResponse:
    def __init__(self, payload: bytes, content_type: str = "application/json") -> None:
        self._payload = payload
        self.headers = SimpleNamespace(
            content_type=content_type,
            get_content_type=lambda: content_type,
        )

    def read(self) -> bytes:
        return self._payload

    def get_content_type(self) -> str:
        return self.headers.get_content_type()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_openrouter_submit_posts_to_videos_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(
            json.dumps(
                {
                    "id": "job-abc",
                    "polling_url": "https://openrouter.ai/api/v1/videos/job-abc",
                    "status": "pending",
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(
        openrouter_module,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key="sk-openrouter",
            openrouter_video_base_url="https://openrouter.ai/api/v1",
        ),
    )
    monkeypatch.setattr(openrouter_module.urllib.request, "urlopen", fake_urlopen)

    provider = OpenRouterVideoProvider()
    job = provider._submit(_video_request())

    assert job.id == "job-abc"
    assert job.status == "pending"
    assert captured["url"] == "https://openrouter.ai/api/v1/videos"
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer sk-openrouter"
    assert captured["body"]["model"] == "bytedance/seedance-2.0-mini"


def test_openrouter_submit_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_module,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key=None,
            openrouter_video_base_url="https://openrouter.ai/api/v1",
        ),
    )
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY não configurada"):
        OpenRouterVideoProvider()._submit(_video_request())


def test_openrouter_poll_returns_status_usage_and_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Any, timeout: int) -> _FakeResponse:
        return _FakeResponse(
            json.dumps(
                {
                    "status": "completed",
                    "unsigned_urls": ["https://cdn.example.com/video.mp4"],
                    "usage": {"cost": 0.12},
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(
        openrouter_module,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key="sk-openrouter",
            openrouter_video_base_url="https://openrouter.ai/api/v1",
        ),
    )
    monkeypatch.setattr(openrouter_module.urllib.request, "urlopen", fake_urlopen)

    update = OpenRouterVideoProvider()._poll(
        VideoJob(id="job-abc", polling_url="https://openrouter.ai/api/v1/videos/job-abc")
    )

    assert update.status == "completed"
    assert update.unsigned_urls == ["https://cdn.example.com/video.mp4"]
    assert update.usage_cost == "0.12"


def test_openrouter_download_writes_video_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    video_bytes = b"\x00\x00\x00\x18ftypmp42"

    def fake_urlopen(request: Any, timeout: int) -> _FakeResponse:
        return _FakeResponse(video_bytes, content_type="video/mp4")

    monkeypatch.setattr(
        openrouter_module,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key="sk-openrouter",
            openrouter_video_base_url="https://openrouter.ai/api/v1",
        ),
    )
    monkeypatch.setattr(openrouter_module.urllib.request, "urlopen", fake_urlopen)

    result = OpenRouterVideoProvider()._download(
        VideoJob(id="job-abc", polling_url=""),
        tmp_path,
    )

    import hashlib

    assert result.file_path.is_file()
    assert result.file_path.read_bytes() == video_bytes
    assert result.content_type == "video/mp4"
    assert result.sha256 == hashlib.sha256(video_bytes).hexdigest()


# ---------------------------------------------------------------------------
# Fluxo de geração dos segmentos
# ---------------------------------------------------------------------------


class _FakeGenerationSession:
    def __init__(self, segment: ContinuousVideoSegment) -> None:
        self.segment = segment
        self.added: list[object] = []
        self.commits = 0
        self.flushes = 0

    def add(self, item: object) -> None:
        if getattr(item, "id", None) is None:
            item.id = uuid4()  # type: ignore[attr-defined]
        self.added.append(item)

    async def get(self, model: object, item_id: object) -> object | None:
        if model is ContinuousVideoSegment and item_id == self.segment.id:
            return self.segment
        if getattr(model, "__name__", "") == "Project":
            return SimpleNamespace(id=item_id, title="Test Project", deleted_at=None)
        return None

    async def execute(self, *args: object, **kwargs: object) -> object:
        class _Result:
            def scalars(self) -> object:
                return SimpleNamespace(first=lambda: None, all=lambda: [])

            def all(self) -> list[Any]:
                return []

        return _Result()

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _item: object) -> None:
        return None


def _generation_segment() -> ContinuousVideoSegment:
    return ContinuousVideoSegment(
        id=uuid4(),
        project_id=uuid4(),
        segment_number=1,
        title="Segmento 01",
        prompt="Clara entra no observatorio.",
        duration_seconds=8,
        status=GenerationJobStatus.SUCCEEDED,
        review_status="ready",
        provider="manual_package",
        model="manual_package",
        request_fingerprint="f" * 64,
        idempotency_key="k" * 64,
        metadata_json={"characters": ["Clara"], "locations": ["Observatorio"]},
    )


@pytest.mark.asyncio
async def test_generate_continuous_video_segments_creates_video_asset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    segment = _generation_segment()
    events: list[dict[str, str]] = []

    async def fake_list(_session: object, requested_project_id: object) -> list[Any]:
        assert requested_project_id == project_id
        return [segment]

    async def fake_production_settings(_session: object, _project_id: object) -> Any:
        return SimpleNamespace(
            video_model="manual_package",
            aspect_ratio="9:16",
            video_resolution="720p",
        )

    async def fake_budget(*args: object, **kwargs: object) -> None:
        return None

    async def fake_emit(*args: object, **kwargs: object) -> None:
        events.append({"status": str(kwargs.get("status", ""))})

    async def fake_submit(
        session: object,
        requested_project_id: object,
        requested_segment: ContinuousVideoSegment,
        production_settings: object,
    ) -> str:
        assert requested_project_id == project_id
        assert requested_segment is segment
        requested_segment.external_operation_id = "job-abc"
        requested_segment.metadata_json = {
            **(requested_segment.metadata_json or {}),
            "video_job_id": "job-abc",
        }
        return "job-abc"

    async def fake_poll(job: object) -> Any:
        assert getattr(job, "id", "") == "job-abc"
        return SimpleNamespace(
            status="completed",
            unsigned_urls=[],
            error=None,
            usage_cost="0.120000",
        )

    async def fake_download(job: object, output_dir: Path) -> Any:
        assert getattr(job, "id", "") == "job-abc"
        output_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
        file_path = output_dir / "video.mp4"
        file_path.write_bytes(b"\x00" * 4)  # noqa: ASYNC240
        return SimpleNamespace(
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256="a" * 64,
            content_type="video/mp4",
            provider="openrouter",
            model="bytedance/seedance-2.0-mini",
            estimated_cost="0.120000",
            job_id="job-abc",
        )

    monkeypatch.setattr(
        continuous_generation,
        "get_settings",
        lambda: SimpleNamespace(
            local_storage_path=tmp_path,
            openrouter_video_model="bytedance/seedance-2.0-mini",
            openrouter_video_generate_audio=True,
            openrouter_api_key="sk-openrouter",
            openrouter_video_base_url="https://openrouter.ai/api/v1",
        ),
    )

    async def fake_prepare(
        _session: object,
        _project_id: object,
        **_kwargs: object,
    ) -> tuple[list[Any], dict[int, list[str]]]:
        return [segment], {}

    monkeypatch.setattr(continuous, "prepare_continuous_video_package", fake_prepare)
    monkeypatch.setattr(continuous_review, "prepare_continuous_video_package", fake_prepare)
    monkeypatch.setattr(continuous, "list_continuous_video_segments", fake_list)
    monkeypatch.setattr(
        continuous_generation,
        "get_or_create_production_settings",
        fake_production_settings,
    )
    monkeypatch.setattr(continuous, "assert_project_budget_allows", fake_budget)
    monkeypatch.setattr(
        continuous_generation,
        "_emit_continuous_video_segment_event",
        fake_emit,
    )
    monkeypatch.setattr(continuous_generation, "_submit_video_job", fake_submit)
    monkeypatch.setattr(continuous_generation, "_poll_video_job", fake_poll)
    monkeypatch.setattr(continuous_generation, "_download_video_job", fake_download)

    session = _FakeGenerationSession(segment)
    generated, errors = await generate_continuous_video_segments(
        cast(AsyncSession, session),
        project_id,
    )

    assert errors == {}
    assert generated == [segment]
    assert segment.status == GenerationJobStatus.SUCCEEDED
    assert segment.review_status == "ready"
    assert segment.provider == "openrouter"
    assert segment.model == "bytedance/seedance-2.0-mini"
    assert segment.generated_video_asset_id is not None
    assert (segment.metadata_json or {}).get("video_asset_id")
    videos = [item for item in session.added if getattr(item, "kind", None) == AssetKind.VIDEO]
    assert len(videos) == 1
    assert videos[0].storage_uri.endswith(".mp4")
    costs = [item for item in session.added if getattr(item, "operation", "") == "video_generation"]
    assert len(costs) == 1
    assert costs[0].provider == "openrouter"
    assert str(costs[0].total_cost) == "0.120000"
    assert any(event["status"] == "video_ready" for event in events)


@pytest.mark.asyncio
async def test_generate_continuous_video_segments_marks_failed_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    segment = _generation_segment()

    async def fake_list(_session: object, requested_project_id: object) -> list[Any]:
        return [segment]

    async def fake_production_settings(_session: object, _project_id: object) -> Any:
        return SimpleNamespace(
            video_model="manual_package",
            aspect_ratio="9:16",
            video_resolution="720p",
        )

    async def fake_budget(*args: object, **kwargs: object) -> None:
        return None

    async def fake_emit(*args: object, **kwargs: object) -> None:
        return None

    async def fake_submit(
        session: object,
        requested_project_id: object,
        requested_segment: ContinuousVideoSegment,
        production_settings: object,
    ) -> str:
        requested_segment.external_operation_id = "job-fail"
        requested_segment.metadata_json = {
            **(requested_segment.metadata_json or {}),
            "video_job_id": "job-fail",
        }
        return "job-fail"

    async def fake_poll(job: object) -> Any:
        return SimpleNamespace(
            status="failed",
            unsigned_urls=[],
            error="provider returned an error",
            usage_cost=None,
        )

    async def fail_download(*args: object, **kwargs: object) -> Any:
        raise AssertionError("não deve baixar vídeo de job falho")

    monkeypatch.setattr(
        continuous_generation,
        "get_settings",
        lambda: SimpleNamespace(
            local_storage_path=tmp_path,
            openrouter_video_model="bytedance/seedance-2.0-mini",
            openrouter_video_generate_audio=True,
            openrouter_api_key="sk-openrouter",
            openrouter_video_base_url="https://openrouter.ai/api/v1",
        ),
    )

    async def fake_prepare(
        _session: object,
        _project_id: object,
        **_kwargs: object,
    ) -> tuple[list[Any], dict[int, list[str]]]:
        return [segment], {}

    monkeypatch.setattr(continuous, "prepare_continuous_video_package", fake_prepare)
    monkeypatch.setattr(continuous_review, "prepare_continuous_video_package", fake_prepare)
    monkeypatch.setattr(continuous, "list_continuous_video_segments", fake_list)
    monkeypatch.setattr(
        continuous_generation,
        "get_or_create_production_settings",
        fake_production_settings,
    )
    monkeypatch.setattr(continuous, "assert_project_budget_allows", fake_budget)
    monkeypatch.setattr(
        continuous_generation,
        "_emit_continuous_video_segment_event",
        fake_emit,
    )
    monkeypatch.setattr(continuous_generation, "_submit_video_job", fake_submit)
    monkeypatch.setattr(continuous_generation, "_poll_video_job", fake_poll)
    monkeypatch.setattr(continuous_generation, "_download_video_job", fail_download)

    session = _FakeGenerationSession(segment)
    generated, errors = await generate_continuous_video_segments(
        cast(AsyncSession, session),
        project_id,
    )

    assert generated == [segment]
    assert segment.status == GenerationJobStatus.FAILED
    assert segment.review_status == "failed"
    assert segment.generated_video_asset_id is None
    assert 1 in errors
    assert "provider returned an error" in errors[1][0]


def test_effective_video_model_uses_project_override() -> None:
    assert (
        continuous_generation._effective_video_model(
            SimpleNamespace(video_model="bytedance/seedance-2.0")
        )
        == "bytedance/seedance-2.0"
    )
    assert (
        continuous_generation._effective_video_model(SimpleNamespace(video_model="manual_package"))
        == "bytedance/seedance-2.0-mini"
    )
    assert (
        continuous_generation._effective_video_model(SimpleNamespace(video_model=""))
        == "bytedance/seedance-2.0-mini"
    )


@pytest.mark.asyncio
async def test_prompt_edit_preserves_exact_full_text_without_changing_action_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    segment = ContinuousVideoSegment(
        id=uuid4(),
        project_id=project_id,
        segment_number=1,
        title="Segmento 01",
        prompt="Prompt anterior.",
        duration_seconds=8,
        status=GenerationJobStatus.SUCCEEDED,
        review_status="ready",
        provider="openrouter",
        model="bytedance/seedance-2.0-mini",
        request_fingerprint="old-fingerprint",
        idempotency_key="old-idempotency-key",
        metadata_json={"action": "Resumo original.", "custom_prompt": False},
    )
    session = _FakeGenerationSession(segment)
    edited_prompt = "Clara abre a porta devagar. Depois do ponto, ela entra e observa toda a sala."

    async def fake_invalidate(*_args: object, **_kwargs: object) -> list[object]:
        return []

    monkeypatch.setattr(
        continuous_review,
        "invalidate_continuous_video_downstream_segments",
        fake_invalidate,
    )

    updated = await continuous_review.update_continuous_video_segment_prompt(
        cast(AsyncSession, session),
        project_id,
        segment.id,
        prompt=edited_prompt,
    )

    assert updated is segment
    assert segment.prompt == edited_prompt
    assert segment.metadata_json["action"] == "Resumo original."
    assert segment.metadata_json["custom_prompt"] is True
