import base64
import json
import urllib.error
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import app.providers.media_utils as media_utils
from app.config.settings import Settings
from app.providers.image.google_ai import (
    DEFAULT_GOOGLE_AI_IMAGE_MAX_ATTEMPTS,
    DEFAULT_GOOGLE_AI_IMAGE_TIMEOUT_SECONDS,
    GoogleAIImageProvider,
)
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


def _http_error(status: int, payload: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://generativelanguage.googleapis.com/v1beta/interactions",
        code=status,
        msg="Error",
        hdrs={},
        fp=BytesIO(payload.encode("utf-8")),
    )


def test_google_ai_image_timeout_budget_stays_bounded_for_ui_flows() -> None:
    assert DEFAULT_GOOGLE_AI_IMAGE_TIMEOUT_SECONDS <= 120
    assert DEFAULT_GOOGLE_AI_IMAGE_MAX_ATTEMPTS <= 2


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
                    "mime_type": "image/jpeg",
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
        "mime_type": "image/jpeg",
        "aspect_ratio": "16:9",
        "image_size": "1K",
    }
    assert result.file_path.read_bytes() == image_bytes
    assert result.file_path.suffix == ".jpg"
    assert result.content_type == "image/jpeg"
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
    assert provider._normalized_aspect_ratio("21:9") == "9:16"
    assert provider._normalized_aspect_ratio("2:1") == "9:16"


def test_google_ai_flash_lite_image_size_is_limited_to_1k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.providers.image.google_ai.get_settings",
        lambda: SimpleNamespace(
            google_ai_image_model="gemini-3.1-flash-lite-image",
            google_ai_image_size="4K",
        ),
    )

    provider = GoogleAIImageProvider()

    assert provider._image_size(None) == "1K"
    assert provider._image_size("3840x2160") == "1K"


@pytest.mark.asyncio
async def test_google_ai_image_provider_coerces_unsupported_aspect_and_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    image_bytes = b"coerced-image"
    encoded_image = base64.b64encode(image_bytes).decode("ascii")

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse:
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _JsonResponse(
            {
                "output_image": {
                    "data": encoded_image,
                    "mime_type": "image/jpeg",
                },
            }
        )

    settings = Settings(
        google_ai_api_key="google-secret",
        google_ai_image_size="4K",
        local_storage_path=tmp_path,
    )
    monkeypatch.setattr("app.providers.image.google_ai.get_settings", lambda: settings)
    monkeypatch.setattr("app.providers.image.google_ai.urllib.request.urlopen", fake_urlopen)

    await GoogleAIImageProvider().generate(
        ImageGenerationRequest(
            prompt="Objeto isolado",
            target_id="prop-1",
            view_type="front",
            output_dir=tmp_path / "out",
            aspect_ratio="1:1",
            resolution="3840x2160",
            model="gemini-3.1-flash-lite-image",
        )
    )

    assert captured["body"]["response_format"]["aspect_ratio"] == "9:16"
    assert captured["body"]["response_format"]["image_size"] == "1K"


def test_google_ai_image_bytes_reads_steps_content() -> None:
    image_bytes = b"steps-image"
    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    response = {
        "id": "interaction-1",
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {"type": "text", "text": "Imagem gerada."},
                    {
                        "type": "image",
                        "data": encoded_image,
                        "mime_type": "image/jpeg",
                    },
                ],
            }
        ],
    }

    decoded, media_type = GoogleAIImageProvider()._image_bytes(response)

    assert decoded == image_bytes
    assert media_type == "image/jpeg"


def test_google_ai_image_bytes_reads_inline_data_content() -> None:
    image_bytes = b"inline-image"
    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    response = {
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "image",
                        "inlineData": {
                            "data": encoded_image,
                            "mimeType": "image/jpeg",
                        },
                    },
                ],
            }
        ],
    }

    decoded, media_type = GoogleAIImageProvider()._image_bytes(response)

    assert decoded == image_bytes
    assert media_type == "image/jpeg"


def test_google_ai_image_provider_retries_transient_http_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    attempts = 0
    sleeps: list[int] = []
    image_bytes = b"retried-image"
    encoded_image = base64.b64encode(image_bytes).decode("ascii")

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _http_error(
                500,
                '{"error":{"message":"Internal error encountered.","code":"api_error"}}',
            )
        return _JsonResponse(
            {
                "steps": [
                    {
                        "content": [
                            {
                                "inlineData": {
                                    "data": encoded_image,
                                    "mimeType": "image/jpeg",
                                },
                            },
                        ],
                    },
                ]
            }
        )

    settings = Settings(
        google_ai_api_key="google-secret",
        google_ai_image_size="1K",
        local_storage_path=tmp_path,
    )
    monkeypatch.setattr("app.providers.image.google_ai.get_settings", lambda: settings)
    monkeypatch.setattr("app.providers.image.google_ai.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(
        "app.providers.image.google_ai.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    result = GoogleAIImageProvider()._generate(
        ImageGenerationRequest(
            prompt="Storyboard frame",
            target_id="shot-1",
            view_type="storyboard_001",
            output_dir=tmp_path / "out",
            model="gemini-3.1-flash-lite-image",
        )
    )

    assert attempts == 2
    assert sleeps == [1]
    assert result.file_path.read_bytes() == image_bytes
