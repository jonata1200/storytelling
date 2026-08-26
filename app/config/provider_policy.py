from collections.abc import Iterable
from typing import Any, Literal

ProviderChannel = Literal["text", "video"]

DEFAULT_PROVIDER = "ollama_cloud"
DEFAULT_VIDEO_PROVIDER = "openrouter"
SUPPORTED_TEXT_PROVIDERS = ("ollama_cloud",)
SUPPORTED_VIDEO_PROVIDERS = ("openrouter",)
SUPPORTED_AI_PROVIDERS = (
    "ollama_cloud",
    "openrouter",
)
SUPPORTED_MODEL_PROVIDERS = frozenset(SUPPORTED_TEXT_PROVIDERS)
MOCK_MODEL_IDS = {
    "mock",
    "mock-llm",
    "mock-image",
    "mock-media",
    "mock-speech",
}


def normalize_api_key(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip()
    if not key:
        return None
    return key


def normalize_provider_name(
    value: object,
    field_name: str = "provider",
    allowed: Iterable[str] = SUPPORTED_AI_PROVIDERS,
) -> str:
    provider = str(value or "").strip().casefold()
    allowed_values = tuple(allowed)
    if provider not in allowed_values:
        allowed_text = ", ".join(allowed_values)
        raise ValueError(f"{field_name} inválido: {provider or '(vazio)'}. Use: {allowed_text}")
    return provider


def effective_provider_for_channel(settings: Any, channel: ProviderChannel) -> str:
    """Resolve the effective provider for a channel using settings."""
    if channel == "video":
        configured_provider = getattr(settings, "video_provider", None) or DEFAULT_VIDEO_PROVIDER
        return normalize_provider_name(
            configured_provider, "VIDEO_PROVIDER", SUPPORTED_VIDEO_PROVIDERS
        )
    channel_provider = getattr(settings, f"{channel}_provider", None)
    configured_provider = channel_provider or getattr(settings, "ai_provider", DEFAULT_PROVIDER)
    return normalize_provider_name(
        configured_provider, f"{channel.upper()}_PROVIDER", SUPPORTED_AI_PROVIDERS
    )


def provider_display_name(provider: str) -> str:
    names = {
        "ollama_cloud": "Ollama Cloud",
        "openrouter": "OpenRouter",
    }
    return names.get(provider, provider)


def provider_api_key(settings: Any, provider: str) -> str | None:
    return normalize_api_key(getattr(settings, f"{provider}_api_key", None))


def provider_model(settings: Any, provider: str, channel: ProviderChannel) -> str:
    suffix_by_channel = {
        "text": "default_model",
        "video": "video_model",
    }
    suffix = suffix_by_channel[channel]
    value = str(getattr(settings, f"{provider}_{suffix}", "") or "").strip()
    if value:
        return value
    return value


def provider_base_url(settings: Any, provider: str) -> str:
    return str(getattr(settings, f"{provider}_base_url", "") or "").strip()


def provider_channel_base_url(settings: Any, provider: str, channel: ProviderChannel) -> str:
    channel_specific = str(getattr(settings, f"{provider}_{channel}_base_url", "") or "").strip()
    if channel_specific:
        return channel_specific
    return provider_base_url(settings, provider)


def provider_requires_api_key(settings: Any, provider: str) -> bool:
    provider_name = str(provider or "").strip().casefold()
    if not provider_name or provider_name in MOCK_MODEL_IDS:
        return False
    return provider_name in SUPPORTED_AI_PROVIDERS


def normalize_model_name(value: object, field_name: str = "modelo") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} não pode ficar vazio")
    if len(text) > 220:
        raise ValueError(f"{field_name} deve ter no maximo 220 caracteres")
    return text


def is_free_model(model: object) -> bool:
    return str(model or "").casefold().endswith(":free")


def is_mock_model(model: object) -> bool:
    text = str(model or "").strip().casefold()
    return text in MOCK_MODEL_IDS or text.startswith("mock-")


def validate_model_name(
    value: object,
    field_name: str = "modelo",
    *,
    provider: str | None = None,
) -> str:
    model = normalize_model_name(value, field_name)
    provider_label = f" da {provider_display_name(provider)}" if provider else ""
    if is_free_model(model):
        raise ValueError(
            f"Modelos free{provider_label} (:free) estão bloqueados. "
            "Escolha um modelo pago/estável para evitar travamentos."
        )
    if is_mock_model(model):
        raise ValueError(
            "Modelos mock estão bloqueados no fluxo da aplicação. "
            f"Configure um modelo real{provider_label}."
        )
    return model


def ensure_provider_api_key(
    api_key: str | None,
    provider: str,
    env_name: str | None = None,
) -> str:
    key = normalize_api_key(api_key)
    if not key:
        variable = env_name or f"{provider.upper()}_API_KEY"
        raise ValueError(
            f"{variable} não configurada. Configure uma chave válida para usar IA real."
        )
    return key
