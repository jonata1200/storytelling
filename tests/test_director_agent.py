import pytest

from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.types import LLMRequest


@pytest.mark.asyncio
async def test_mock_director_agent_uses_section_and_project_context() -> None:
    result = await MockLLMProvider().generate_structured(
        LLMRequest(
            task="director_agent_chat",
            prompt="Ajude com o storyboard",
            variables={
                "section": "storyboard",
                "message": "Crie uma segunda versão",
                "project_context": {"summary": "1 roteiro e 8 quadros"},
            },
        )
    )

    assert "storyboard" in result.content["message"]
    assert "1 roteiro e 8 quadros" in result.content["message"]
