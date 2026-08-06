from pathlib import Path

import pytest

from app.core.enums import GenerationJobStatus
from app.providers.image.mock import MockImageProvider
from app.providers.image.types import ImageGenerationRequest
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.types import LLMRequest
from app.providers.speech.mock import MockSpeechProvider
from app.providers.speech.types import SpeechRequest
from app.providers.video.mock import MockVideoProvider
from app.providers.video.types import VideoRequest


@pytest.mark.asyncio
async def test_mock_image_provider_creates_svg_reference(tmp_path: Path) -> None:
    provider = MockImageProvider()

    result = await provider.generate(
        ImageGenerationRequest(
            prompt="Personagem principal, retrato frontal",
            target_id="char_test",
            view_type="front_portrait",
            output_dir=tmp_path,
            aspect_ratio="16:9",
        )
    )

    assert result.file_path.exists()
    assert result.content_type == "image/svg+xml"
    assert len(result.sha256) == 64
    assert "front_portrait" in result.file_path.name
    svg = result.file_path.read_text(encoding="utf-8")
    assert 'width="1920" height="1080"' in svg


@pytest.mark.asyncio
async def test_mock_llm_provider_generates_story_idea_contract() -> None:
    provider = MockLLMProvider()

    result = await provider.generate_structured(
        LLMRequest(
            task="generate_story_ideas",
            prompt="",
            variables={
                "theme": "perdao",
                "audience": "adultos",
                "primary_emotion": "esperanca",
                "target_duration_minutes": 7,
            },
        )
    )

    assert result.provider == "mock"
    assert len(result.content["ideas"]) == 3
    assert result.content["ideas"][0]["retention_potential"] > 0
    assert {idea["duration_minutes"] for idea in result.content["ideas"]} == {7}


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


@pytest.mark.asyncio
async def test_mock_video_provider_generates_mockvideo_file(tmp_path: Path) -> None:
    provider = MockVideoProvider()

    result = await provider.generate_from_image(
        VideoRequest(
            prompt="Storyboard emotional close up",
            duration_seconds=4,
            source_image_uri="asset://frame",
            output_dir=tmp_path,
        )
    )

    assert result.status == GenerationJobStatus.SUCCEEDED
    assert result.file_path is not None
    assert result.file_path.exists()
    assert result.sha256 is not None
    assert provider.capabilities.image_to_video
