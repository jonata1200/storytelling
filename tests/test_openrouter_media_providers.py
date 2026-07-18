import base64
from pathlib import Path
from typing import Any

from app.config.settings import Settings
from app.core.enums import GenerationJobStatus
from app.providers.image.openrouter import OpenRouterImageProvider
from app.providers.image.types import ImageGenerationRequest
from app.providers.video.openrouter import OpenRouterVideoProvider
from app.providers.video.types import VideoRequest


def test_openrouter_image_provider_writes_generated_image(
    monkeypatch: Any, tmp_path: Path
) -> None:
    provider = OpenRouterImageProvider()
    pixel = base64.b64encode(b"fake-png").decode("ascii")

    monkeypatch.setattr(
        "app.providers.image.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="key"),
    )
    monkeypatch.setattr(
        provider,
        "_post_json",
        lambda path, body: {
            "data": [{"b64_json": pixel, "media_type": "image/png"}],
            "usage": {"cost": 0.02},
        },
    )

    result = provider._generate(
        ImageGenerationRequest(
            prompt="dramatic character portrait",
            target_id="char",
            view_type="front",
            output_dir=tmp_path,
            model="google/gemini-2.5-flash-image",
        )
    )

    assert result.provider == "openrouter"
    assert result.content_type == "image/png"
    assert result.file_path.exists()
    assert result.file_path.read_bytes() == b"fake-png"
    assert result.estimated_cost == "0.02"


def test_openrouter_video_provider_downloads_completed_video(
    monkeypatch: Any, tmp_path: Path
) -> None:
    provider = OpenRouterVideoProvider()
    posted: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.providers.video.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="key"),
    )

    def fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        posted.update({"path": path, "body": body})
        return {
            "id": "job-1",
            "status": "completed",
            "unsigned_urls": ["/content"],
            "usage": {"cost": 1.5},
        }

    monkeypatch.setattr(provider, "_post_json", fake_post)
    monkeypatch.setattr(provider, "_download", lambda path: b"fake-mp4")

    result = provider._generate(
        VideoRequest(
            prompt="camera pushes in",
            duration_seconds=4,
            source_image_uri="asset://frame",
            output_dir=tmp_path,
            model="google/veo-3.1",
            size="1080x1920",
        ),
        image_to_video=True,
    )

    assert posted["path"] == "/videos"
    assert posted["body"]["model"] == "google/veo-3.1"
    assert posted["body"]["size"] == "1080x1920"
    assert result.status == GenerationJobStatus.SUCCEEDED
    assert result.file_path is not None
    assert result.file_path.read_bytes() == b"fake-mp4"
    assert result.estimated_cost == "1.5"
