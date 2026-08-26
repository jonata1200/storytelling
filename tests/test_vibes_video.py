import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

import app.providers.video.types as video_types
import app.providers.video.vibes as vibes_module
from app.config.settings import Settings
from app.providers.registry import resolve_video_provider
from app.providers.video.types import (
    VideoGenerationRequest,
    VideoGenerationResult,
    VideoImageInput,
    VideoIngredientInput,
    VideoJob,
    VideoJobUpdate,
)
from app.providers.video.vibes import VibesVideoProvider
from app.providers.video.vibes_mapping import map_vibes_request
from app.vibes.ingredients import mark_ingredient_synced
from app.visual_bible.models import VisualReference


def _request(storage: Path) -> VideoGenerationRequest:
    return VideoGenerationRequest(
        model="vibes",
        prompt="Uma praça ao amanhecer",
        duration=8,
        aspect_ratio="9:16",
        generate_audio=True,
        frame_images=[VideoImageInput(url="data:image/png;base64,AA==", frame_type="first_frame")],
        input_references=[VideoImageInput(url="data:image/png;base64,AQ==")],
        ingredients=[VideoIngredientInput(id="ing-1", type="character", reference_id="ref-1")],
        output_dir=storage / "generated_videos",
    )


class FakeBrowserBackend:
    def __init__(self, storage: Path, *, corrupt: bool = False) -> None:
        self.storage = storage
        self.corrupt = corrupt
        self.payload: dict[str, object] = {}

    async def submit(self, payload: dict[str, object]) -> VideoJob:
        self.payload = payload
        return VideoJob(id="job-123", status="pending")

    async def poll(self, job: VideoJob) -> VideoJobUpdate:
        return VideoJobUpdate(status="completed", usage_cost="0.25")

    async def download(self, job: VideoJob, output_dir: Path) -> VideoGenerationResult:
        output_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
        content = b"invalid" if self.corrupt else b"\x00\x00\x00\x18ftypmp42test"
        path = output_dir / "vibe.mp4"
        path.write_bytes(content)  # noqa: ASYNC240
        return VideoGenerationResult(
            file_path=path,
            storage_uri=path.as_posix(),
            sha256=hashlib.sha256(content).hexdigest(),
            content_type="video/mp4",
            provider="vibes",
            model="vibes",
            prompt="prompt",
            job_id=job.id,
        )


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    storage = tmp_path / "storage"
    settings = Settings(
        _env_file=None,
        local_storage_path=storage,
        video_provider="vibes",
        vibes_integration_mode="browser",
    )
    monkeypatch.setattr(video_types, "get_settings", lambda: settings)
    monkeypatch.setattr(vibes_module, "get_settings", lambda: settings)
    return storage


def test_vibes_request_mapping(configured: Path) -> None:
    payload = map_vibes_request(_request(configured))
    assert payload["duration_seconds"] == 10
    assert payload["aspect_ratio"] == "portrait"
    assert payload["first_frame"] == "data:image/png;base64,AA=="
    assert payload["ingredients"] == [{"id": "ing-1", "type": "character", "reference_id": "ref-1"}]


async def test_vibes_contract_submit_poll_download(configured: Path) -> None:
    backend = FakeBrowserBackend(configured)
    provider = VibesVideoProvider(backend)
    request = _request(configured)

    job = await provider.submit(request)
    update = await provider.poll(job)
    result = await provider.download(job, request.output_dir)

    assert job.id == "job-123"
    assert job.provider == "vibes"
    assert update.status == "completed"
    assert result.file_path.is_file()
    assert backend.payload["audio"] == {"enabled": True}


async def test_vibes_rejects_corrupt_download(configured: Path) -> None:
    provider = VibesVideoProvider(FakeBrowserBackend(configured, corrupt=True))
    request = _request(configured)
    job = await provider.submit(request)
    with pytest.raises(ValueError, match="corrompido"):
        await provider.download(job, request.output_dir)


async def test_vibes_api_mode_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        local_storage_path=tmp_path / "storage",
        vibes_integration_mode="api",
        vibes_api_key="secret",
    )
    monkeypatch.setattr(video_types, "get_settings", lambda: settings)
    monkeypatch.setattr(vibes_module, "get_settings", lambda: settings)
    with pytest.raises(RuntimeError, match="não possui API pública"):
        await VibesVideoProvider().submit(_request(settings.local_storage_path))


def test_registry_resolves_vibes() -> None:
    provider = resolve_video_provider(Settings(_env_file=None), "vibes")
    assert provider.provider_name == "vibes"


def test_default_vibes_readiness_does_not_claim_unconfigured_browser_is_ready() -> None:
    from app.observability.service import _provider_channel_readiness

    readiness = _provider_channel_readiness(Settings(_env_file=None), "video")
    assert readiness.status == "degraded"
    assert "VIBES_BROWSER_AUTOMATION_ENABLED" in readiness.message


def test_ingredient_sync_is_idempotent_and_keeps_history() -> None:
    reference = VisualReference(
        project_id=uuid4(),
        artifact_id=uuid4(),
        asset_id=uuid4(),
        target_kind="character",
        target_id=uuid4(),
        view_type="portrait",
        prompt="Ana",
        provider="meta",
        model="image",
        status="approved",
        metadata_json={},
    )
    assert mark_ingredient_synced(reference, ingredient_id="ing-1", ingredient_type="character")
    assert not mark_ingredient_synced(reference, ingredient_id="ing-1", ingredient_type="character")
    assert mark_ingredient_synced(reference, ingredient_id="ing-2", ingredient_type="character")
    assert reference.metadata_json["vibes"]["history"][0]["ingredient_id"] == "ing-1"
