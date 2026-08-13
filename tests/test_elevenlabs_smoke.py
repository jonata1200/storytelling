import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.providers.speech.elevenlabs import ElevenLabsSpeechProvider
from app.providers.speech.types import SpeechRequest


@pytest.mark.provider
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_elevenlabs_speech_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if os.getenv("RUN_ELEVENLABS_SPEECH_SMOKE") != "1" or not os.getenv("ELEVENLABS_API_KEY"):
        pytest.skip("Defina RUN_ELEVENLABS_SPEECH_SMOKE=1 e ELEVENLABS_API_KEY para rodar.")
    if not os.getenv("ELEVENLABS_VOICE_ID"):
        pytest.skip("Defina ELEVENLABS_VOICE_ID para rodar o smoke de voz.")

    settings = Settings(
        elevenlabs_api_key=os.environ["ELEVENLABS_API_KEY"],
        elevenlabs_voice_id=os.environ["ELEVENLABS_VOICE_ID"],
        elevenlabs_speech_model=os.getenv("ELEVENLABS_SPEECH_MODEL", "eleven_multilingual_v2"),
    )
    monkeypatch.setattr("app.providers.speech.elevenlabs.get_settings", lambda: settings)

    result = await ElevenLabsSpeechProvider().synthesize(
        SpeechRequest(
            text="Teste rapido de voz para o fluxo de storytelling.",
            voice_profile_id=settings.elevenlabs_voice_id,
            output_dir=tmp_path,
            model=settings.elevenlabs_speech_model,
        )
    )

    assert result.file_path.exists()
    assert result.file_path.stat().st_size > 0
