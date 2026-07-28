import pytest

from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.types import LLMRequest


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
