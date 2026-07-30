from app.config.settings import get_settings
from app.providers.llm.openai_compatible import (
    OpenAICompatibleLLMConfig,
    OpenAICompatibleLLMProvider,
)


class GroqLLMProvider(OpenAICompatibleLLMProvider):
    provider_name = "groq"
    display_name = "Groq"

    def _provider_config(self) -> OpenAICompatibleLLMConfig:
        settings = get_settings()
        return OpenAICompatibleLLMConfig(
            provider_name=self.provider_name,
            display_name=self.display_name,
            base_url=settings.groq_base_url,
            api_key=settings.groq_api_key,
            api_key_env="GROQ_API_KEY",
            require_api_key=True,
        )
