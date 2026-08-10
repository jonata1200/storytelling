import base64
import json
import urllib.error
from email.message import Message
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

import app.providers.media_utils as media_utils
from app.config.settings import Settings
from app.core.enums import GenerationJobStatus
from app.providers.video.google_ai import GoogleAIVideoProvider
from app.providers.video.types import VideoRequest


class _JsonResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _BytesResponse:
    def __init__(self, payload: bytes, content_type: str = "video/mp4") -> None:
        self._payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self) -> "_BytesResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _http_error(status: int, payload: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://generativelanguage.googleapis.com/v1beta/models/"
        "veo-3.1-lite-generate-preview:predictLongRunning",
        code=status,
        msg="Error",
        hdrs=Message(),
        fp=BytesIO(payload.encode("utf-8")),
    )


@pytest.mark.asyncio
async def test_google_ai_video_provider_submits_polls_and_saves_inline_video(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {"polls": 0}
    source = tmp_path / "frame.png"
    source.write_bytes(b"source-frame")
    video_bytes = b"video-bytes"
    encoded_video = base64.b64encode(video_bytes).decode("ascii")

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse:
        captured.setdefault("timeouts", []).append(timeout)
        if request.get_method() == "POST":
            captured["submit_url"] = request.full_url
            captured["submit_headers"] = dict(request.header_items())
            captured["submit_body"] = json.loads(request.data.decode("utf-8"))
            return _JsonResponse({"name": "operations/video-1"})

        captured["polls"] += 1
        captured.setdefault("poll_urls", []).append(request.full_url)
        if captured["polls"] == 1:
            return _JsonResponse({"done": False})
        return _JsonResponse(
            {
                "done": True,
                "response": {
                    "generateVideoResponse": {
                        "generatedSamples": [
                            {
                                "video": {
                                    "inlineData": {
                                        "mimeType": "video/mp4",
                                        "data": encoded_video,
                                    }
                                }
                            }
                        ]
                    }
                },
            }
        )

    settings = Settings(
        google_ai_api_key="google-secret",
        google_ai_video_poll_interval_seconds=1,
        google_ai_video_poll_timeout_seconds=5,
        local_storage_path=tmp_path,
    )
    monkeypatch.setattr("app.providers.video.google_ai.get_settings", lambda: settings)
    monkeypatch.setattr(media_utils, "get_settings", lambda: settings)
    monkeypatch.setattr("app.providers.video.google_ai.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("app.providers.video.google_ai.urllib.request.urlopen", fake_urlopen)

    result = await GoogleAIVideoProvider().generate_from_image(
        VideoRequest(
            prompt="Animar a cena",
            duration_seconds=7,
            aspect_ratio="16:9",
            resolution="1920x1080",
            source_image_uri=source.as_posix(),
            output_dir=tmp_path / "videos",
            model="veo-3.1-lite-generate-preview",
            seed=123,
        )
    )

    assert captured["submit_url"] == (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/veo-3.1-lite-generate-preview:predictLongRunning"
    )
    assert captured["submit_headers"]["X-goog-api-key"] == "google-secret"
    assert captured["submit_body"]["instances"][0]["prompt"] == "Animar a cena"
    assert captured["submit_body"]["instances"][0]["image"]["inlineData"]["mimeType"] == (
        "image/png"
    )
    assert captured["submit_body"]["parameters"] == {
        "aspectRatio": "16:9",
        "durationSeconds": "8",
        "numberOfVideos": 1,
        "resolution": "720p",
        "seed": 123,
    }
    assert captured["poll_urls"] == [
        "https://generativelanguage.googleapis.com/v1beta/operations/video-1",
        "https://generativelanguage.googleapis.com/v1beta/operations/video-1",
    ]
    assert result.status == GenerationJobStatus.SUCCEEDED
    assert result.external_job_id == "operations/video-1"
    assert result.file_path is not None
    assert result.file_path.read_bytes() == video_bytes
    assert result.provider == "google_ai"
    assert result.metadata["delivery"] == "inline"
    assert result.metadata["duration_seconds"] == 8


@pytest.mark.asyncio
async def test_google_ai_video_provider_downloads_uri_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloaded = b"downloaded-video"

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse | _BytesResponse:
        if request.get_method() == "POST":
            return _JsonResponse({"name": "operations/video-2"})
        if request.full_url.endswith("/operations/video-2"):
            return _JsonResponse(
                {
                    "done": True,
                    "response": {
                        "generateVideoResponse": {
                            "generatedSamples": [
                                {
                                    "video": {
                                        "uri": "https://generativelanguage.googleapis.com/v1beta/files/video"
                                    }
                                }
                            ]
                        }
                    },
                }
            )
        return _BytesResponse(downloaded)

    settings = Settings(
        google_ai_api_key="google-secret",
        google_ai_video_poll_interval_seconds=1,
        google_ai_video_poll_timeout_seconds=5,
    )
    monkeypatch.setattr("app.providers.video.google_ai.get_settings", lambda: settings)
    monkeypatch.setattr("app.providers.video.google_ai.urllib.request.urlopen", fake_urlopen)

    result = await GoogleAIVideoProvider().generate_from_text(
        VideoRequest(
            prompt="Cena ampla",
            duration_seconds=4,
            output_dir=tmp_path,
            model="veo-3.1-lite-generate-preview",
        )
    )

    assert result.file_path is not None
    assert result.file_path.read_bytes() == downloaded
    assert result.metadata["delivery"] == "uri"


def test_google_ai_video_request_coerces_legacy_resolution_to_720p() -> None:
    body = GoogleAIVideoProvider()._request_body(
        VideoRequest(
            prompt="Cena ampla",
            duration_seconds=4,
            resolution="1920x1080",
            output_dir=Path("videos"),
            model="veo-3.1-lite-generate-preview",
        ),
        image_to_video=False,
    )

    assert body["parameters"]["durationSeconds"] == "4"
    assert body["parameters"]["resolution"] == "720p"


def test_google_ai_video_request_keeps_720p_image_input_duration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "frame.png"
    source.write_bytes(b"source-frame")
    settings = Settings(local_storage_path=tmp_path)
    monkeypatch.setattr(media_utils, "get_settings", lambda: settings)

    body = GoogleAIVideoProvider()._request_body(
        VideoRequest(
            prompt="Animar frame",
            duration_seconds=4,
            resolution="720p",
            source_image_uri=source.as_posix(),
            output_dir=tmp_path,
            model="veo-3.1-lite-generate-preview",
        ),
        image_to_video=True,
    )

    assert body["parameters"]["durationSeconds"] == "4"
    assert body["parameters"]["resolution"] == "720p"


def test_google_ai_video_request_sends_reference_images(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "frame.png"
    reference = tmp_path / "clara.png"
    source.write_bytes(b"source-frame")
    reference.write_bytes(b"reference-frame")
    settings = Settings(local_storage_path=tmp_path)
    monkeypatch.setattr(media_utils, "get_settings", lambda: settings)

    body = GoogleAIVideoProvider()._request_body(
        VideoRequest(
            prompt="Animar frame",
            duration_seconds=8,
            resolution="720p",
            source_image_uri=source.as_posix(),
            reference_uris=[reference.as_posix()],
            output_dir=tmp_path,
            model="veo-3.1-lite-generate-preview",
        ),
        image_to_video=True,
    )

    reference_images = body["instances"][0]["referenceImages"]
    assert len(reference_images) == 1
    assert reference_images[0]["referenceType"] == "asset"
    assert body["parameters"]["durationSeconds"] == "8"


@pytest.mark.asyncio
async def test_google_ai_video_provider_retries_transient_submit_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    attempts = 0
    sleeps: list[int] = []
    video_bytes = b"video-after-retry"
    encoded_video = base64.b64encode(video_bytes).decode("ascii")

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse:
        nonlocal attempts
        if request.get_method() == "POST":
            attempts += 1
            if attempts == 1:
                raise _http_error(
                    500,
                    '{"error":{"message":"Internal error encountered.","code":"api_error"}}',
                )
            return _JsonResponse({"name": "operations/video-retry"})
        return _JsonResponse(
            {
                "done": True,
                "response": {
                    "generatedVideos": [
                        {
                            "video": {
                                "inlineData": {
                                    "mimeType": "video/mp4",
                                    "data": encoded_video,
                                }
                            }
                        }
                    ]
                },
            }
        )

    settings = Settings(
        google_ai_api_key="google-secret",
        google_ai_video_poll_interval_seconds=1,
        google_ai_video_poll_timeout_seconds=5,
    )
    monkeypatch.setattr("app.providers.video.google_ai.get_settings", lambda: settings)
    monkeypatch.setattr("app.providers.video.google_ai.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(
        "app.providers.video.google_ai.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    result = await GoogleAIVideoProvider().generate_from_text(
        VideoRequest(
            prompt="Cena ampla",
            duration_seconds=4,
            output_dir=tmp_path,
            model="veo-3.1-lite-generate-preview",
        )
    )

    assert attempts == 2
    assert sleeps == [1]
    assert result.file_path is not None
    assert result.file_path.read_bytes() == video_bytes


@pytest.mark.asyncio
async def test_google_ai_video_provider_retries_transient_poll_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    poll_attempts = 0
    sleeps: list[int] = []
    video_bytes = b"video-after-poll-retry"
    encoded_video = base64.b64encode(video_bytes).decode("ascii")

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse:
        nonlocal poll_attempts
        if request.get_method() == "POST":
            return _JsonResponse({"name": "operations/video-poll-retry"})
        poll_attempts += 1
        if poll_attempts == 1:
            raise _http_error(503, '{"error":{"message":"temporarily unavailable"}}')
        return _JsonResponse(
            {
                "done": True,
                "response": {
                    "generatedVideos": [
                        {
                            "video": {
                                "inlineData": {
                                    "mimeType": "video/mp4",
                                    "data": encoded_video,
                                }
                            }
                        }
                    ]
                },
            }
        )

    settings = Settings(
        google_ai_api_key="google-secret",
        google_ai_video_poll_interval_seconds=1,
        google_ai_video_poll_timeout_seconds=5,
    )
    monkeypatch.setattr("app.providers.video.google_ai.get_settings", lambda: settings)
    monkeypatch.setattr("app.providers.video.google_ai.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(
        "app.providers.video.google_ai.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    result = await GoogleAIVideoProvider().generate_from_text(
        VideoRequest(
            prompt="Cena ampla",
            duration_seconds=4,
            output_dir=tmp_path,
            model="veo-3.1-lite-generate-preview",
        )
    )

    assert poll_attempts == 2
    assert sleeps == [1]
    assert result.file_path is not None
    assert result.file_path.read_bytes() == video_bytes


@pytest.mark.asyncio
async def test_google_ai_video_provider_retries_transient_download_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    download_attempts = 0
    sleeps: list[int] = []
    downloaded = b"download-after-retry"

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse | _BytesResponse:
        nonlocal download_attempts
        if request.get_method() == "POST":
            return _JsonResponse({"name": "operations/video-download-retry"})
        if request.full_url.endswith("/operations/video-download-retry"):
            return _JsonResponse(
                {
                    "done": True,
                    "response": {
                        "generateVideoResponse": {
                            "generatedSamples": [
                                {
                                    "video": {
                                        "uri": "https://generativelanguage.googleapis.com/v1beta/files/video"
                                    }
                                }
                            ]
                        }
                    },
                }
            )
        download_attempts += 1
        if download_attempts == 1:
            raise _http_error(502, '{"error":{"message":"bad gateway"}}')
        return _BytesResponse(downloaded)

    settings = Settings(
        google_ai_api_key="google-secret",
        google_ai_video_poll_interval_seconds=1,
        google_ai_video_poll_timeout_seconds=5,
    )
    monkeypatch.setattr("app.providers.video.google_ai.get_settings", lambda: settings)
    monkeypatch.setattr("app.providers.video.google_ai.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(
        "app.providers.video.google_ai.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    result = await GoogleAIVideoProvider().generate_from_text(
        VideoRequest(
            prompt="Cena ampla",
            duration_seconds=4,
            output_dir=tmp_path,
            model="veo-3.1-lite-generate-preview",
        )
    )

    assert download_attempts == 2
    assert sleeps == [1]
    assert result.file_path is not None
    assert result.file_path.read_bytes() == downloaded
