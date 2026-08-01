import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.providers.dubbing.elevenlabs import ElevenLabsDubbingProvider
from app.providers.dubbing.types import DubbingSubmitRequest
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


@pytest.mark.provider
@pytest.mark.smoke
def test_elevenlabs_dubbing_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.getenv("RUN_ELEVENLABS_DUBBING_SMOKE") != "1":
        pytest.skip("Defina RUN_ELEVENLABS_DUBBING_SMOKE=1 para rodar.")
    if not os.getenv("ELEVENLABS_API_KEY"):
        pytest.skip("Defina ELEVENLABS_API_KEY para rodar o smoke de dublagem.")
    source_path = Path(os.getenv("ELEVENLABS_DUBBING_SOURCE_FILE", ""))
    if not source_path.is_file():
        pytest.skip("Defina ELEVENLABS_DUBBING_SOURCE_FILE para um arquivo de video/audio local.")

    settings = Settings(
        elevenlabs_api_key=os.environ["ELEVENLABS_API_KEY"],
        dubbing_source_lang=os.getenv("DUBBING_SOURCE_LANG", "pt"),
        dubbing_target_lang=os.getenv("DUBBING_TARGET_LANG", "en"),
    )
    monkeypatch.setattr("app.providers.dubbing.elevenlabs.get_settings", lambda: settings)

    submit = ElevenLabsDubbingProvider().submit(
        DubbingSubmitRequest(
            file_path=source_path,
            name="storytelling-smoke",
            source_language=settings.dubbing_source_lang,
            target_language=settings.dubbing_target_lang,
        )
    )

    assert submit.external_job_id
