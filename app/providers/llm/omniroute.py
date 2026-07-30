import urllib.request

from app.config.settings import get_settings
from app.providers.llm.openai_compatible import (
    OpenAICompatibleLLMConfig,
    OpenAICompatibleLLMProvider,
    OpenAICompatibleResponseFormatError,
)

OmniRouteResponseFormatError = OpenAICompatibleResponseFormatError


class OmniRouteLLMProvider(OpenAICompatibleLLMProvider):
    provider_name = "omniroute"
    display_name = "OmniRoute"

    def _provider_config(self) -> OpenAICompatibleLLMConfig:
        settings = get_settings()
        return OpenAICompatibleLLMConfig(
            provider_name=self.provider_name,
            display_name=self.display_name,
            base_url=settings.omniroute_base_url,
            api_key=settings.omniroute_api_key,
            api_key_env="OMNIROUTE_API_KEY",
            require_api_key=True,
        )

    def _urlopen(
        self,
        request: urllib.request.Request,
        timeout_seconds: float,
    ) -> object:
        return urllib.request.urlopen(request, timeout=timeout_seconds)
