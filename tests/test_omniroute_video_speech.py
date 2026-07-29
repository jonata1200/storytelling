from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.config.settings import Settings
from app.core.enums import GenerationJobStatus
from app.providers.speech import omniroute as speech_omniroute
from app.providers.speech.omniroute import OmniRouteSpeechProvider
from app.providers.speech.service import (
    speech_configuration_status,
    speech_model_from_settings,
    speech_provider_from_settings,
)
from app.providers.speech.types import SpeechRequest
from app.providers.video.omniroute import OmniRouteVideoProvider
from app.providers.video.types import VideoRequest
from app.video_generation import service as video_service


def test_omniroute_video_provider_downloads_completed_image_to_video(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider = OmniRouteVideoProvider()
    storage_root = tmp_path / "storage"
    frame_dir = storage_root / "frames"
    frame_dir.mkdir(parents=True)
    frame = frame_dir / "frame.png"
    frame.write_bytes(b"fake-frame")
    posted: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.providers.video.omniroute.get_settings",
        lambda: Settings(
            omniroute_api_key="omni-secret",
            local_storage_path=storage_root,
        ),
    )
    monkeypatch.setattr(
        "app.providers.media_utils.get_settings",
        lambda: Settings(local_storage_path=storage_root),
    )

    def fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        posted.update({"path": path, "body": body})
        return {
            "task_id": "task-1",
            "status": "completed",
            "data": {"urls": ["/content/task-1.mp4"]},
            "usage": {"cost": "2.50"},
        }

    monkeypatch.setattr(provider, "_post_json", fake_post)
    monkeypatch.setattr(provider, "_download", lambda path: b"fake-mp4")

    result = provider._generate(
        VideoRequest(
            prompt="camera pushes in",
            duration_seconds=5,
            source_image_uri=frame.as_posix(),
            output_dir=tmp_path,
            model="veo-free/veo",
            size="1080x1920",
        ),
        image_to_video=True,
    )

    assert posted["path"] == "/videos"
    assert posted["body"]["seconds"] == "5"
    assert posted["body"]["resolution"] == "1080p"
    assert posted["body"]["aspect_ratio"] == "9:16"
    assert posted["body"]["audio_generation"] == "Disabled"
    assert posted["body"]["enable_bgm"] == "Disabled"
    assert posted["body"]["keep_original_sound"] == "Disabled"
    assert posted["body"]["firstframe"].startswith("data:image/png;base64,")
    assert posted["body"]["images"][0].startswith("data:image/png;base64,")
    assert result.provider == "omniroute"
    assert result.status == GenerationJobStatus.SUCCEEDED
    assert result.file_path is not None
    assert result.file_path.read_bytes() == b"fake-mp4"
    assert result.estimated_cost == "2.50"


def test_omniroute_video_provider_reports_failed_task(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OmniRouteVideoProvider()
    monkeypatch.setattr(
        "app.providers.video.omniroute.get_settings",
        lambda: Settings(omniroute_api_key="omni-secret"),
    )

    with pytest.raises(RuntimeError, match="job failed"):
        provider._wait_until_complete(
            "task-1",
            {"task_id": "task-1", "status": "failed", "message": "quota exceeded"},
        )


@pytest.mark.asyncio
async def test_video_provider_for_project_uses_omniroute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_production_settings(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            video_model="mock-video",
            aspect_ratio="9:16",
            video_resolution="1080x1920",
        )

    monkeypatch.setattr(
        video_service,
        "get_or_create_production_settings",
        fake_production_settings,
    )
    monkeypatch.setattr(
        video_service,
        "get_settings",
        lambda: Settings(
            ai_provider="omniroute",
            video_provider="omniroute",
            omniroute_api_key="omni-secret",
            omniroute_video_model="veo-free/veo",
        ),
    )

    provider, provider_name, model, directory, aspect_ratio, resolution = (
        await video_service._video_provider_for_project(
            object(),  # type: ignore[arg-type]
            uuid4(),
            "auto",
            None,
        )
    )

    assert getattr(provider, "provider_name", None) == "omniroute"
    assert provider_name == "omniroute"
    assert model == "veo-free/veo"
    assert directory == "omniroute_videos"
    assert aspect_ratio == "9:16"
    assert resolution == "1080x1920"


class _CapturingOmniRouteSpeechProvider(OmniRouteSpeechProvider):
    def __init__(self) -> None:
        self.body: dict[str, Any] | None = None

    def _post_speech(self, base_url: str, api_key: str, body: dict[str, Any]) -> bytes:
        assert base_url == "https://omnirouters.com/v1"
        assert api_key == "omni-secret"
        self.body = body
        return b"RIFFfake-wave"


@pytest.mark.asyncio
async def test_omniroute_speech_provider_writes_audio_and_uses_voice_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        speech_omniroute,
        "get_settings",
        lambda: Settings(
            speech_provider="omniroute",
            omniroute_api_key="omni-secret",
            omniroute_base_url="https://omnirouters.com/v1",
            omniroute_speech_model="tts-model",
            speech_voice="default-voice",
        ),
    )
    provider = _CapturingOmniRouteSpeechProvider()

    result = await provider.synthesize(
        SpeechRequest(
            text="Ola mundo",
            voice_profile_id="voz-clara",
            output_dir=tmp_path,
            model="tts-model",
        )
    )

    assert result.file_path.exists()
    assert result.provider == "omniroute"
    assert result.model == "tts-model"
    assert result.alignment["words"]
    assert provider.body is not None
    assert provider.body["voice"] == "voz-clara"
    assert provider.body["response_format"] == "wav"


def test_speech_service_accepts_omniroute_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        speech_provider="omniroute",
        omniroute_api_key="omni-secret",
        omniroute_speech_model="tts-model",
    )
    monkeypatch.setattr("app.providers.speech.service.get_settings", lambda: settings)

    provider = speech_provider_from_settings()
    ready, message, details = speech_configuration_status(settings)

    assert getattr(provider, "provider_name", None) == "omniroute"
    assert ready is True
    assert "OmniRoute" in message
    assert details == {"provider": "omniroute", "model": "tts-model"}
    assert speech_model_from_settings(settings) == "tts-model"
