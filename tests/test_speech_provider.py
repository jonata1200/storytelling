from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.providers.speech import openai_compatible
from app.providers.speech.openai_compatible import OpenAICompatibleSpeechProvider
from app.providers.speech.types import SpeechRequest


class _CapturingSpeechProvider(OpenAICompatibleSpeechProvider):
    def __init__(self) -> None:
        self.body: dict[str, Any] | None = None

    def _post_speech(self, base_url: str, api_key: str, body: dict[str, Any]) -> bytes:
        self.body = body
        return b"RIFFfake-wave"


@pytest.mark.asyncio
async def test_openai_compatible_speech_provider_writes_audio_and_alignment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        openai_compatible,
        "get_settings",
        lambda: SimpleNamespace(
            speech_api_key="sk-test",
            speech_model="speech-model",
            speech_voice="default-voice",
            speech_base_url="https://speech.example/v1",
            speech_timeout_seconds=5,
        ),
    )
    provider = _CapturingSpeechProvider()

    result = await provider.synthesize(
        SpeechRequest(
            text="Ola mundo",
            voice_profile_id="narrador",
            output_dir=tmp_path,
            model="speech-model",
        )
    )

    assert result.file_path.exists()
    assert result.provider == "openai_compatible"
    assert result.alignment["words"]
    assert provider.body is not None
    assert provider.body["voice"] == "narrador"
