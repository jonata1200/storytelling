import base64
import urllib.error
from pathlib import Path
from typing import Any

import pytest

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
    posted: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.providers.image.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test"),
    )
    def fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        posted.update({"path": path, "body": body})
        return {
            "data": [{"b64_json": pixel, "media_type": "image/png"}],
            "usage": {"cost": 0.02},
        }

    monkeypatch.setattr(provider, "_post_json", fake_post)

    result = provider._generate(
        ImageGenerationRequest(
            prompt="dramatic character portrait",
            target_id="char",
            view_type="front",
            output_dir=tmp_path,
            aspect_ratio="1:1",
            resolution="1080x1920",
            model="sourceful/riverflow-v2.5-pro",
        )
    )

    assert posted["path"] == "/images"
    assert posted["body"]["aspect_ratio"] == "1:1"
    assert posted["body"]["resolution"] == "2K"
    assert result.provider == "openrouter"
    assert result.content_type == "image/png"
    assert result.file_path.exists()
    assert result.file_path.read_bytes() == b"fake-png"
    assert result.estimated_cost == "0.02"


def test_openrouter_image_provider_retries_with_jpeg_when_png_is_rejected(
    monkeypatch: Any, tmp_path: Path
) -> None:
    provider = OpenRouterImageProvider()
    pixel = base64.b64encode(b"fake-jpeg").decode("ascii")
    posted_bodies: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "app.providers.image.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test"),
    )

    def fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        assert path == "/images"
        posted_bodies.append(dict(body))
        if len(posted_bodies) == 1:
            raise RuntimeError(
                "OpenRouter Images HTTP 400: output_format not supported. Accepted: jpeg"
            )
        return {"data": [{"b64_json": pixel}], "usage": {"cost": 0.03}}

    monkeypatch.setattr(provider, "_post_json", fake_post)

    result = provider._generate(
        ImageGenerationRequest(
            prompt="dramatic character portrait",
            target_id="char",
            view_type="front",
            output_dir=tmp_path,
            aspect_ratio="9:16",
            model="sourceful/riverflow-v2.5-fast",
        )
    )

    assert [body["output_format"] for body in posted_bodies] == ["png", "jpeg"]
    assert result.content_type == "image/jpeg"
    assert result.file_path.suffix == ".jpg"
    assert result.file_path.read_bytes() == b"fake-jpeg"


def test_openrouter_image_provider_writes_webp_with_displayable_extension(
    monkeypatch: Any, tmp_path: Path
) -> None:
    provider = OpenRouterImageProvider()
    pixel = base64.b64encode(b"fake-webp").decode("ascii")

    monkeypatch.setattr(
        "app.providers.image.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test"),
    )
    monkeypatch.setattr(
        provider,
        "_post_json",
        lambda _path, _body: {
            "data": [{"b64_json": pixel, "media_type": "image/webp"}],
        },
    )

    result = provider._generate(
        ImageGenerationRequest(
            prompt="vertical storyboard",
            target_id="shot",
            view_type="storyboard_001",
            output_dir=tmp_path,
            model="sourceful/riverflow-v2-fast",
        )
    )

    assert result.content_type == "image/webp"
    assert result.file_path.suffix == ".webp"
    assert result.file_path.read_bytes() == b"fake-webp"


def test_openrouter_image_provider_retries_without_n_when_rejected_with_single_quotes(
    monkeypatch: Any, tmp_path: Path
) -> None:
    provider = OpenRouterImageProvider()
    pixel = base64.b64encode(b"fake-png").decode("ascii")
    posted_bodies: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "app.providers.image.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test"),
    )

    def fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        assert path == "/images"
        posted_bodies.append(dict(body))
        if len(posted_bodies) == 1:
            raise RuntimeError("OpenRouter Images HTTP 400: unsupported parameter: 'n'")
        return {"data": [{"b64_json": pixel, "media_type": "image/png"}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)

    result = provider._generate(
        ImageGenerationRequest(
            prompt="dramatic character portrait",
            target_id="char",
            view_type="front",
            output_dir=tmp_path,
            model="bytedance-seed/seedream-4.5",
        )
    )

    assert "n" in posted_bodies[0]
    assert "n" not in posted_bodies[1]
    assert result.file_path.read_bytes() == b"fake-png"


def test_openrouter_image_provider_retries_without_unsupported_aspect_ratio(
    monkeypatch: Any, tmp_path: Path
) -> None:
    provider = OpenRouterImageProvider()
    pixel = base64.b64encode(b"fake-png").decode("ascii")
    posted_bodies: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "app.providers.image.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test"),
    )

    def fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        assert path == "/images"
        posted_bodies.append(dict(body))
        if len(posted_bodies) == 1:
            raise RuntimeError("OpenRouter Images HTTP 400: unsupported parameter: aspect_ratio")
        return {"data": [{"b64_json": pixel, "media_type": "image/png"}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)

    result = provider._generate(
        ImageGenerationRequest(
            prompt="dramatic character portrait",
            target_id="char",
            view_type="front",
            output_dir=tmp_path,
            aspect_ratio="9:16",
            model="sourceful/riverflow-v2.5-pro",
        )
    )

    assert "aspect_ratio" in posted_bodies[0]
    assert "aspect_ratio" not in posted_bodies[1]
    assert posted_bodies[1]["output_format"] == "png"
    assert result.file_path.read_bytes() == b"fake-png"


def test_openrouter_image_provider_retries_multiple_unsupported_parameters(
    monkeypatch: Any, tmp_path: Path
) -> None:
    provider = OpenRouterImageProvider()
    pixel = base64.b64encode(b"fake-png").decode("ascii")
    posted_bodies: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "app.providers.image.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test"),
    )

    def fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        assert path == "/images"
        posted_bodies.append(dict(body))
        if len(posted_bodies) == 1:
            raise RuntimeError(
                "OpenRouter Images HTTP 400: unsupported parameters: output_format, aspect_ratio"
            )
        return {"data": [{"b64_json": pixel, "media_type": "image/png"}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)

    result = provider._generate(
        ImageGenerationRequest(
            prompt="dramatic character portrait",
            target_id="char",
            view_type="front",
            output_dir=tmp_path,
            aspect_ratio="16:9",
            model="sourceful/riverflow-v2.5-pro",
        )
    )

    assert {"output_format", "aspect_ratio"}.issubset(posted_bodies[0])
    assert "output_format" not in posted_bodies[1]
    assert "aspect_ratio" not in posted_bodies[1]
    assert result.file_path.read_bytes() == b"fake-png"


def test_openrouter_image_provider_retries_without_unsupported_resolution(
    monkeypatch: Any, tmp_path: Path
) -> None:
    provider = OpenRouterImageProvider()
    pixel = base64.b64encode(b"fake-png").decode("ascii")
    posted_bodies: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "app.providers.image.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test"),
    )

    def fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        assert path == "/images"
        posted_bodies.append(dict(body))
        if len(posted_bodies) == 1:
            raise RuntimeError("OpenRouter Images HTTP 400: unsupported parameter: resolution")
        return {"data": [{"b64_json": pixel, "media_type": "image/png"}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)

    result = provider._generate(
        ImageGenerationRequest(
            prompt="dramatic character portrait",
            target_id="char",
            view_type="front",
            output_dir=tmp_path,
            resolution="1080x1920",
            model="sourceful/riverflow-v2-fast",
        )
    )

    assert "resolution" in posted_bodies[0]
    assert "resolution" not in posted_bodies[1]
    assert result.file_path.read_bytes() == b"fake-png"


def test_openrouter_image_provider_retries_without_invalid_resolution(
    monkeypatch: Any, tmp_path: Path
) -> None:
    provider = OpenRouterImageProvider()
    pixel = base64.b64encode(b"fake-png").decode("ascii")
    posted_bodies: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "app.providers.image.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test"),
    )

    def fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        assert path == "/images"
        posted_bodies.append(dict(body))
        if len(posted_bodies) == 1:
            raise RuntimeError(
                'OpenRouter Images HTTP 400: {"error":{"message":"Invalid option: '
                'expected one of \\"512\\"|\\"1K\\"|\\"2K\\"|\\"4K\\"","path":["resolution"]}}'
            )
        return {"data": [{"b64_json": pixel, "media_type": "image/png"}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)

    result = provider._generate(
        ImageGenerationRequest(
            prompt="dramatic character portrait",
            target_id="char",
            view_type="front",
            output_dir=tmp_path,
            resolution="unusual",
            model="sourceful/riverflow-v2-fast",
        )
    )

    assert posted_bodies[0]["resolution"] == "unusual"
    assert "resolution" not in posted_bodies[1]
    assert result.file_path.read_bytes() == b"fake-png"


def test_openrouter_image_provider_wraps_network_errors(
    monkeypatch: Any,
) -> None:
    provider = OpenRouterImageProvider()
    monkeypatch.setattr(
        "app.providers.image.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test"),
    )

    def raise_url_error(*args: object, **kwargs: object) -> None:
        raise urllib.error.URLError("temporary failure in name resolution")

    monkeypatch.setattr("app.providers.image.openrouter.urllib.request.urlopen", raise_url_error)

    with pytest.raises(RuntimeError, match="network error"):
        provider._post_json("/images", {"model": "model", "prompt": "prompt"})


def test_openrouter_image_provider_rejects_invalid_base64(
    monkeypatch: Any, tmp_path: Path
) -> None:
    provider = OpenRouterImageProvider()
    monkeypatch.setattr(
        "app.providers.image.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test"),
    )
    monkeypatch.setattr(
        provider,
        "_post_json",
        lambda path, body: {"data": [{"b64_json": "not valid base64"}]},
    )

    with pytest.raises(RuntimeError, match="b64_json invalido"):
        provider._generate(
            ImageGenerationRequest(
                prompt="dramatic character portrait",
                target_id="char",
                view_type="front",
                output_dir=tmp_path,
                model="bytedance-seed/seedream-4.5",
            )
        )


def test_openrouter_video_provider_downloads_completed_video(
    monkeypatch: Any, tmp_path: Path
) -> None:
    provider = OpenRouterVideoProvider()
    posted: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.providers.video.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test"),
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
            model="bytedance/seedance-2.0-fast",
            size="1080x1920",
        ),
        image_to_video=True,
    )

    assert posted["path"] == "/videos"
    assert posted["body"]["model"] == "bytedance/seedance-2.0-fast"
    assert posted["body"]["size"] == "1080x1920"
    assert result.status == GenerationJobStatus.SUCCEEDED
    assert result.file_path is not None
    assert result.file_path.read_bytes() == b"fake-mp4"
    assert result.estimated_cost == "1.5"


def test_openrouter_video_provider_declares_seedance_duration_range() -> None:
    provider = OpenRouterVideoProvider()

    assert provider.capabilities.supported_durations == list(range(4, 16))


def test_openrouter_video_provider_rejects_invalid_duration(
    monkeypatch: Any, tmp_path: Path
) -> None:
    provider = OpenRouterVideoProvider()
    monkeypatch.setattr(
        "app.providers.video.openrouter.get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test"),
    )

    with pytest.raises(ValueError, match="4 a 15"):
        provider._generate(
            VideoRequest(
                prompt="camera pushes in",
                duration_seconds=16,
                output_dir=tmp_path,
                model="bytedance/seedance-2.0-fast",
            ),
            image_to_video=False,
        )
