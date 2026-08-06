import os

import pytest

from app.config.settings import get_settings
from app.generation.model_settings import configured_text_llm_provider
from app.providers.llm.types import LLMRequest


@pytest.mark.provider
@pytest.mark.smoke
@pytest.mark.skipif(
    os.getenv("STORYTELLING_TEXT_PROVIDER_SMOKE") != "1",
    reason="Set STORYTELLING_TEXT_PROVIDER_SMOKE=1 to call the configured text provider.",
)
@pytest.mark.asyncio
async def test_configured_text_provider_real_smoke() -> None:
    settings = get_settings()
    provider, model, provider_name = configured_text_llm_provider(settings)

    result = await provider.generate_structured(
        LLMRequest(
            task="generate_story_ideas",
            prompt='Retorne somente este JSON: {"ok": true}',
            model=model,
            timeout_seconds=60,
        )
    )

    assert provider_name == "ollama_cloud"
    assert result.content.get("ok") is True
