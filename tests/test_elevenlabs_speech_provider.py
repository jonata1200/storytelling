import base64
import json
from pathlib import Path
from typing import Any

import pytest

from app.config.settings import Settings
from app.providers.speech import elevenlabs as speech_elevenlabs
from app.providers.speech.elevenlabs import ElevenLabsSpeechProvider
from app.providers.speech.service import (
    speech_configuration_status,
    speech_model_from_settings,
    speech_provider_from_settings,
)
from app.providers.speech.types import SpeechRequest


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
async def test_elevenlabs_speech_provider_writes_audio_and_alignment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    audio = base64.b64encode(b"mp3-audio").decode("ascii")

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _JsonResponse(
            {
                "audio_base64": audio,
                "alignment": {
                    "characters": ["O", "i"],
                    "character_start_times_seconds": [0, 0.1],
                    "character_end_times_seconds": [0.1, 1.4],
                },
            }
        )

    settings = Settings(
        elevenlabs_api_key="eleven-secret",
        elevenlabs_voice_id="default-voice",
        elevenlabs_speech_model="eleven_multilingual_v2",
        elevenlabs_output_format="mp3_44100_128",
        speech_timeout_seconds=7,
    )
    monkeypatch.setattr(speech_elevenlabs, "get_settings", lambda: settings)
    monkeypatch.setattr(speech_elevenlabs.urllib.request, "urlopen", fake_urlopen)

    result = await ElevenLabsSpeechProvider().synthesize(
        SpeechRequest(
            text="Oi",
            voice_profile_id="voice-123",
            output_dir=tmp_path,
            model="eleven_multilingual_v2",
        )
    )

    assert captured["url"].startswith(
        "https://api.elevenlabs.io/v1/text-to-speech/voice-123/with-timestamps"
    )
    assert "output_format=mp3_44100_128" in captured["url"]
    assert captured["headers"]["Xi-api-key"] == "eleven-secret"
    assert captured["body"]["text"] == "Oi"
    assert captured["body"]["model_id"] == "eleven_multilingual_v2"
    assert result.file_path.read_bytes() == b"mp3-audio"
    assert result.content_type == "audio/mpeg"
    assert result.duration_seconds == 1
    assert result.alignment["characters"] == ["O", "i"]
    assert result.estimated_cost == "0.000200"


def test_speech_service_accepts_elevenlabs_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        speech_provider="elevenlabs",
        elevenlabs_api_key="eleven-secret",
        elevenlabs_voice_id="voice-default",
        elevenlabs_speech_model="eleven_flash_v2_5",
    )
    monkeypatch.setattr("app.providers.speech.service.get_settings", lambda: settings)

    provider = speech_provider_from_settings()
    ready, message, details = speech_configuration_status(settings)

    assert getattr(provider, "provider_name", None) == "elevenlabs"
    assert ready is True
    assert "ElevenLabs" in message
    assert details == {"provider": "elevenlabs", "model": "eleven_flash_v2_5"}
    assert speech_model_from_settings(settings) == "eleven_flash_v2_5"
