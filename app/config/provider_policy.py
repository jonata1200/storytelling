from collections.abc import Iterable
from typing import Any, Literal
from urllib.parse import urlparse

ProviderChannel = Literal["text", "image", "video", "speech"]

DEFAULT_PROVIDER = "ollama"
LEGACY_AI_PROVIDERS = ("omniroute", "opencode")
SUPPORTED_TEXT_PROVIDERS = ("ollama", "groq", "nvidia_nim")
SUPPORTED_MEDIA_PROVIDERS = ("veo_ai_free",)
SUPPORTED_AI_PROVIDERS = (
    "ollama",
    "groq",
    "nvidia_nim",
    "veo_ai_free",
)
SUPPORTED_MODEL_PROVIDERS = frozenset(SUPPORTED_TEXT_PROVIDERS)
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
    return key


def normalize_provider_name(
    value: object,
    field_name: str = "provider",
    allowed: Iterable[str] = SUPPORTED_AI_PROVIDERS,
) -> str:
    provider = str(value or "").strip().casefold()
    if provider in LEGACY_AI_PROVIDERS:
        return DEFAULT_PROVIDER
    allowed_values = tuple(allowed)
    if provider not in allowed_values:
        allowed_text = ", ".join(allowed_values)
        raise ValueError(f"{field_name} inválido: {provider or '(vazio)'}. Use: {allowed_text}")
    return provider


def effective_provider_for_channel(settings: Any, channel: ProviderChannel) -> str:
    channel_provider = getattr(settings, f"{channel}_provider", None)
    configured_provider = channel_provider or getattr(settings, "ai_provider", DEFAULT_PROVIDER)
    configured_text = str(configured_provider or "").strip().casefold()
    if configured_text in LEGACY_AI_PROVIDERS:
        return "veo_ai_free" if channel in {"image", "video"} else DEFAULT_PROVIDER
    if channel in {"image", "video"} and not channel_provider:
        return "veo_ai_free"
    return normalize_provider_name(configured_provider, f"{channel.upper()}_PROVIDER")


def provider_display_name(provider: str) -> str:
    names = {
        "omniroute": "OmniRoute",
        "ollama": "Ollama",
        "groq": "Groq",
        "nvidia_nim": "NVIDIA NIM",
        "veo_ai_free": "Veo AI Free",
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


def is_ollama_cloud_base_url(base_url: object) -> bool:
    value = str(base_url or "").strip()
    if not value:
        return False
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.casefold().removeprefix("www.")
    return host == "ollama.com"


def provider_requires_api_key(settings: Any, provider: str) -> bool:
    if provider == "ollama":
        return is_ollama_cloud_base_url(provider_base_url(settings, provider))
    if provider == "nvidia_nim":
        base_url = provider_base_url(settings, provider).casefold()
        return "integrate.api.nvidia.com" in base_url
    if provider == "veo_ai_free":
        return False
    return True


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
