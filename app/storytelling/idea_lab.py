from app.config.settings import get_settings
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.openrouter import OpenRouterLLMProvider
from app.providers.llm.types import LLMRequest


async def generate_freeform_ideas(
    theme: str,
    genre: str,
    emotion: str,
) -> list[dict]:
    settings = get_settings()
    provider = OpenRouterLLMProvider() if settings.openrouter_api_key else MockLLMProvider()
    result = await provider.generate_structured(
        LLMRequest(
            task="generate_story_ideas",
            model=settings.openrouter_default_model,
            prompt=(
                "Gere exatamente três ideias de histórias originais em português do Brasil. "
                f"Tema: {theme}. Gênero: {genre}. Emoção principal: {emotion}. "
                "Retorne JSON com a chave ideas; cada ideia deve ter title, hook, premise, "
                "protagonist, retention_potential, cliche_risk e production_complexity."
            ),
            variables={
                "theme": theme,
                "genre": genre,
                "primary_emotion": emotion,
                "audience": "público geral",
            },
            output_schema={"type": "object", "properties": {"ideas": {"type": "array"}}},
        )
    )
    return list(result.content.get("ideas") or [])
