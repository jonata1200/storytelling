from app.config.provider_policy import provider_integration_mode, provider_requires_api_key
from app.config.settings import get_settings
from app.providers.llm.openai_compatible import (
    OpenAICompatibleLLMConfig,
    OpenAICompatibleLLMProvider,
)


class MetaLLMProvider(OpenAICompatibleLLMProvider):
    """Meta Model API adapter over its documented OpenAI-compatible interface."""

    provider_name = "meta"
    display_name = "Meta Model API"

    def _provider_config(self) -> OpenAICompatibleLLMConfig:
        settings = get_settings()
        mode = provider_integration_mode(settings, self.provider_name, "text")
        if mode != "api":
            raise ValueError(
                "Meta Text requer META_INTEGRATION_MODE=api; browser é permitido apenas "
                "para capacidades explicitamente autorizadas."
            )
        base_url = str(settings.meta_base_url or "").strip()
        if not base_url:
            raise ValueError(
                "META_BASE_URL não configurada. Copie a URL base exibida pela documentação "
                "oficial da Meta Model API para a sua conta."
            )
        return OpenAICompatibleLLMConfig(
            provider_name=self.provider_name,
            display_name=self.display_name,
            base_url=base_url,
            api_key=settings.meta_api_key,
            api_key_env="META_API_KEY",
            require_api_key=provider_requires_api_key(settings, self.provider_name),
            allow_response_format_fallback=False,
        )
