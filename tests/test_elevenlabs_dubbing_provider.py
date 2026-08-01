import json
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from app.config.settings import Settings
from app.providers.dubbing import elevenlabs as dubbing_elevenlabs
from app.providers.dubbing.elevenlabs import ElevenLabsDubbingProvider
from app.providers.dubbing.types import DubbingSubmitRequest


class _JsonResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"

    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _BytesResponse:
    def __init__(self, payload: bytes, content_type: str) -> None:
        self._payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self) -> "_BytesResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_elevenlabs_dubbing_provider_submit_status_and_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    media = tmp_path / "export.mp4"
    media.write_bytes(b"video")

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse | _BytesResponse:
        calls.append(
            {
                "method": request.get_method(),
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "body": getattr(request, "data", b""),
                "timeout": timeout,
            }
        )
        if request.get_method() == "POST":
            return _JsonResponse({"dubbing_id": "dub-1", "expected_duration_sec": 12.5})
        if request.full_url.endswith("/dubbing/dub-1"):
            return _JsonResponse(
                {
                    "dubbing_id": "dub-1",
                    "status": "dubbed",
                    "source_language": "pt",
                    "target_languages": ["en"],
                }
            )
        return _BytesResponse(b"dubbed-video", "video/mp4")

    settings = Settings(
        elevenlabs_api_key="eleven-secret",
        dubbing_poll_timeout_seconds=15,
    )
    monkeypatch.setattr(dubbing_elevenlabs, "get_settings", lambda: settings)
    monkeypatch.setattr(dubbing_elevenlabs.urllib.request, "urlopen", fake_urlopen)

    provider = ElevenLabsDubbingProvider()
    submit = provider.submit(
        DubbingSubmitRequest(
            file_path=media,
            name="Export",
            source_language="pt",
            target_language="en",
        )
    )
    status = provider.status(submit.external_job_id)
    download = provider.download(submit.external_job_id, "en")

    assert submit.external_job_id == "dub-1"
    assert submit.expected_duration_seconds == 12.5
    assert status.status == "dubbed"
    assert status.target_languages == ["en"]
    assert download.content == b"dubbed-video"
    assert download.content_type == "video/mp4"
    assert calls[0]["url"] == "https://api.elevenlabs.io/v1/dubbing"
    assert calls[0]["headers"]["Xi-api-key"] == "eleven-secret"
    assert b'name="target_lang"' in calls[0]["body"]
    assert b"export.mp4" in calls[0]["body"]
    assert calls[2]["url"] == "https://api.elevenlabs.io/v1/dubbing/dub-1/audio/en"
