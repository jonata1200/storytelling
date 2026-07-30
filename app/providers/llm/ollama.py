from app.config.settings import get_settings
from app.providers.llm.openai_compatible import (
    OpenAICompatibleLLMConfig,
    OpenAICompatibleLLMProvider,
)


class OllamaLLMProvider(OpenAICompatibleLLMProvider):
    provider_name = "ollama"
    display_name = "Ollama"

    def _provider_config(self) -> OpenAICompatibleLLMConfig:
        settings = get_settings()
        return OpenAICompatibleLLMConfig(
            provider_name=self.provider_name,
            display_name=self.display_name,
            base_url=settings.ollama_base_url,
            api_key=settings.ollama_api_key or "ollama",
            api_key_env="OLLAMA_API_KEY",
            require_api_key=False,
        )
