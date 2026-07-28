from collections.abc import Iterable
from typing import Any, Literal

ProviderChannel = Literal["text", "image", "video", "speech"]

DEFAULT_PROVIDER = "omniroute"
SUPPORTED_AI_PROVIDERS = ("openrouter", "omniroute")
SUPPORTED_MODEL_PROVIDERS = frozenset(SUPPORTED_AI_PROVIDERS)
MOCK_MODEL_IDS = {
    "mock",
    "mock-llm",
    "mock-image",
    "mock-video",
    "mock-speech",
}


def normalize_api_key(value: str | None, provider: str) -> str | None:
    if not value:
        return None
    key = value.strip()
    if not key:
        return None
    if provider == "openrouter" and not key.startswith("sk-or-"):
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
    channel_provider = getattr(settings, f"{channel}_provider", None)
    configured_provider = channel_provider or getattr(settings, "ai_provider", DEFAULT_PROVIDER)
    return normalize_provider_name(configured_provider, f"{channel.upper()}_PROVIDER")


def provider_display_name(provider: str) -> str:
    names = {
        "openrouter": "OpenRouter",
        "omniroute": "OmniRoute",
    }
    return names.get(provider, provider)


def provider_api_key(settings: Any, provider: str) -> str | None:
    return normalize_api_key(getattr(settings, f"{provider}_api_key", None), provider)


def provider_model(settings: Any, provider: str, channel: ProviderChannel) -> str:
    suffix_by_channel = {
        "text": "default_model",
        "image": "image_model",
        "video": "video_model",
        "speech": "speech_model",
    }
    suffix = suffix_by_channel[channel]
    return str(getattr(settings, f"{provider}_{suffix}", "") or "").strip()


def provider_base_url(settings: Any, provider: str) -> str:
    return str(getattr(settings, f"{provider}_base_url", "") or "").strip()


def normalize_model_name(value: object, field_name: str = "modelo") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} não pode ficar vazio")
    if len(text) > 220:
        raise ValueError(f"{field_name} deve ter no maximo 220 caracteres")
    return text


def is_free_model(model: object) -> bool:
    return ":free" in str(model or "").casefold()


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
    key = normalize_api_key(api_key, provider)
    if not key:
        variable = env_name or f"{provider.upper()}_API_KEY"
        raise ValueError(
            f"{variable} não configurada. Configure uma chave válida para usar IA real."
        )
    return key


def unavailable_provider_error(provider: str, phase: str) -> ValueError:
    display_name = provider_display_name(provider)
    return ValueError(
        f"{display_name} já pode ser configurado, mas as chamadas reais ainda serão "
        f"ativadas na {phase}. Use OpenRouter como fallback temporário."
    )
