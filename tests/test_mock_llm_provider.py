import pytest

from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.types import LLMRequest
from app.video_generation.durations import VIDEO_CLIP_MAX_SECONDS, VIDEO_CLIP_MIN_SECONDS


@pytest.mark.asyncio
async def test_mock_llm_generates_three_story_ideas() -> None:
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
async def test_mock_llm_generates_scenes_with_shots() -> None:
    provider = MockLLMProvider()

    result = await provider.generate_structured(
        LLMRequest(
            task="generate_scenes_and_shots",
            prompt="",
            variables={"target_duration_seconds": 240},
        )
    )

    scenes = result.content["scenes"]
    assert len(scenes) == 5
    shots = [shot for scene in scenes for shot in scene["shots"]]
    assert sum(shot["duration_seconds"] for shot in shots) == 240
    assert all(
        VIDEO_CLIP_MIN_SECONDS <= shot["duration_seconds"] <= VIDEO_CLIP_MAX_SECONDS
        for shot in shots
    )
    assert all(
        scene["duration_seconds"] == sum(shot["duration_seconds"] for shot in scene["shots"])
        for scene in scenes
    )


@pytest.mark.asyncio
async def test_mock_llm_generates_cinematic_script_format() -> None:
    provider = MockLLMProvider()

    result = await provider.generate_structured(
        LLMRequest(
            task="generate_script",
            prompt="",
            variables={
                "idea": {"title": "A promessa"},
                "narrative_contract": {"title": "A promessa"},
                "language": "pt-BR",
                "target_duration_seconds": 300,
            },
        )
    )

    content = result.content["content"]
    assert "FADE IN:" in content
    assert "CENA 01" in content
    assert "INT. CASA DA FAMILIA" in content
    assert "EXT. RUA ESTREITA" in content
    assert "CLARA\n" in content
    assert "FADE OUT." in content
    assert " - 60s" not in content
    assert " - 300s" not in content
    assert "OBJETIVO DRAMATICO" not in content
    assert "INDICACAO PARA STORYBOARD" not in content


@pytest.mark.asyncio
async def test_mock_llm_scales_script_scene_count_with_duration() -> None:
    provider = MockLLMProvider()

    result = await provider.generate_structured(
        LLMRequest(
            task="generate_script",
            prompt="",
            variables={
                "idea": {"title": "A promessa longa"},
                "narrative_contract": {"title": "A promessa longa"},
                "language": "pt-BR",
                "target_duration_seconds": 900,
                "expected_scene_count": 12,
            },
        )
    )

    content = result.content["content"]
    assert content.count("CENA ") == 12
    assert "CENA 12" in content
