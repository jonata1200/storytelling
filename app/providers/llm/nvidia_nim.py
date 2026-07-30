from app.config.provider_policy import provider_requires_api_key
from app.config.settings import get_settings
from app.providers.llm.openai_compatible import (
    OpenAICompatibleLLMConfig,
    OpenAICompatibleLLMProvider,
)


class NvidiaNimLLMProvider(OpenAICompatibleLLMProvider):
    provider_name = "nvidia_nim"
    display_name = "NVIDIA NIM"

    def _provider_config(self) -> OpenAICompatibleLLMConfig:
        settings = get_settings()
        return OpenAICompatibleLLMConfig(
            provider_name=self.provider_name,
            display_name=self.display_name,
            base_url=settings.nvidia_nim_base_url,
            api_key=settings.nvidia_nim_api_key,
            api_key_env="NVIDIA_NIM_API_KEY",
            require_api_key=provider_requires_api_key(settings, self.provider_name),
        )
