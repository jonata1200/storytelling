import os
from time import perf_counter

import pytest

from app.config.settings import get_settings
from app.generation.model_settings import configured_text_llm_provider
from app.providers.llm.types import LLMRequest

SMOKE_TASKS = (
    "generate_story_ideas",
    "generate_story_hooks",
    "generate_script",
    "generate_scenes_and_shots",
    "generate_storyboard_prompts",
    "visual_bible_extraction",
)


@pytest.mark.provider
@pytest.mark.smoke
@pytest.mark.skipif(
    os.getenv("STORYTELLING_META_TEXT_SMOKE") != "1",
    reason="Set STORYTELLING_META_TEXT_SMOKE=1 to call the real Meta Model API.",
)
@pytest.mark.parametrize("task", SMOKE_TASKS)
@pytest.mark.asyncio
async def test_meta_structured_text_tasks_real_smoke(task: str) -> None:
    settings = get_settings()
    provider, model, provider_name = configured_text_llm_provider(settings)
    assert provider_name == "meta"

    started = perf_counter()
    result = await provider.generate_structured(
        LLMRequest(
            task=task,
            prompt=(
                "Teste de integração. Responda em português brasileiro somente com "
                'este JSON válido: {"ok": true, "task": "' + task + '"}'
            ),
            model=model,
            timeout_seconds=120,
            output_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "task": {"type": "string"},
                },
                "required": ["ok", "task"],
                "additionalProperties": False,
            },
        )
    )
    duration_seconds = perf_counter() - started

    assert result.content == {"ok": True, "task": task}
    assert result.provider == "meta"
    assert duration_seconds > 0
