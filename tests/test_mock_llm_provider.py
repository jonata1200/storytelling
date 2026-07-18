import pytest

from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.types import LLMRequest


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
    assert len(scenes) == 4
    assert all(len(scene["shots"]) == 3 for scene in scenes)


@pytest.mark.asyncio
async def test_mock_llm_generates_cinematic_script_format() -> None:
    provider = MockLLMProvider()

    result = await provider.generate_structured(
        LLMRequest(
            task="generate_script",
            prompt="",
            variables={
                "story_bible": {"title": "A promessa"},
                "language": "pt-BR",
                "target_duration_seconds": 300,
            },
        )
    )

    content = result.content["content"]
    assert "CENA 01" in content
    assert "OBJETIVO DRAMATICO" in content
    assert "ELEMENTOS VISUAIS" in content
    assert "INDICACAO PARA STORYBOARD" in content
    assert "INDICACAO PARA VIDEO" in content
    assert "INT. CASA DA FAMILIA" in content
    assert "EXT. RUA ESTREITA" in content
    assert "CLARA\n" in content
