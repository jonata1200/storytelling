from pathlib import Path

import pytest

from app.providers.speech.mock import MockSpeechProvider
from app.providers.speech.types import SpeechRequest


@pytest.mark.asyncio
async def test_mock_speech_provider_generates_wav_and_alignment(tmp_path: Path) -> None:
    provider = MockSpeechProvider()

    result = await provider.synthesize(
        SpeechRequest(
            text="Uma narracao curta para teste",
            voice_profile_id="voice-test",
            output_dir=tmp_path,
        )
    )

    assert result.content_type == "audio/wav"
    assert result.file_path.exists()
    assert result.file_path.suffix == ".wav"
    assert len(result.sha256) == 64
    assert result.alignment["words"][0]["word"] == "Uma"
