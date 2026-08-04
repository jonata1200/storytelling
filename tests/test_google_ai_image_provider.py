import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import app.providers.media_utils as media_utils
from app.config.settings import Settings
from app.providers.image.google_ai import GoogleAIImageProvider
from app.providers.image.types import ImageGenerationRequest


class _JsonResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


@pytest.mark.asyncio
async def test_google_ai_image_provider_generates_and_saves_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    source = tmp_path / "reference.png"
    source.write_bytes(b"source-image")
    image_bytes = b"generated-image"
    encoded_image = base64.b64encode(image_bytes).decode("ascii")

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _JsonResponse(
            {
                "output_image": {
                    "data": encoded_image,
                    "mime_type": "image/png",
                },
                "usage": {"cost": "0.03"},
            }
        )

    settings = Settings(
        google_ai_api_key="google-secret",
        google_ai_image_size="512px",
        local_storage_path=tmp_path,
    )
    monkeypatch.setattr("app.providers.image.google_ai.get_settings", lambda: settings)
    monkeypatch.setattr(media_utils, "get_settings", lambda: settings)
    monkeypatch.setattr("app.providers.image.google_ai.urllib.request.urlopen", fake_urlopen)

    result = await GoogleAIImageProvider().generate(
        ImageGenerationRequest(
            prompt="Frame cinematico",
            negative_prompt="sem texto",
            target_id="char-1",
            view_type="portrait",
            output_dir=tmp_path / "out",
            aspect_ratio="16:9",
            resolution="3840x2160",
            references=[source.as_posix()],
            model="gemini-3.1-flash-lite-image",
        )
    )

    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert captured["headers"]["X-goog-api-key"] == "google-secret"
    assert captured["body"]["model"] == "gemini-3.1-flash-lite-image"
    assert captured["body"]["input"][0]["text"].startswith("Frame cinematico")
    assert captured["body"]["input"][1]["mime_type"] == "image/png"
    assert captured["body"]["response_format"] == {
        "type": "image",
        "mime_type": "image/png",
        "aspect_ratio": "16:9",
        "image_size": "4K",
    }
    assert result.file_path.read_bytes() == image_bytes
    assert result.content_type == "image/png"
    assert result.provider == "google_ai"
    assert result.estimated_cost == "0.03"


def test_google_ai_image_size_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.providers.image.google_ai.get_settings",
        lambda: SimpleNamespace(google_ai_image_size="0.5K"),
    )

    provider = GoogleAIImageProvider()

    assert provider._image_size(None) == "512px"
    assert provider._image_size("2048x2048") == "2K"
    assert provider._normalized_aspect_ratio("21:9") == "21:9"
    assert provider._normalized_aspect_ratio("2:1") == "9:16"
