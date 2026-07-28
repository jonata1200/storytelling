from typing import Any

from app.config.settings import get_settings
from app.providers.speech.omniroute import OmniRouteSpeechProvider
from app.providers.speech.openai_compatible import OpenAICompatibleSpeechProvider
from app.providers.speech.types import SpeechProvider


def speech_provider_from_settings() -> SpeechProvider:
    provider_name = speech_provider_name()
    if provider_name in {"openai_compatible", "openai-compatible"}:
        return OpenAICompatibleSpeechProvider()
    if provider_name == "omniroute":
        return OmniRouteSpeechProvider()
    if provider_name == "mock":
        raise ValueError("Provider mock de voz está bloqueado no fluxo de audio real.")
    raise ValueError(f"Provider de voz não suportado: {provider_name}")


def speech_provider_name(settings: Any | None = None) -> str:
    app_settings = settings or get_settings()
    return str(app_settings.speech_provider or "").strip().lower()


def speech_model_from_settings(settings: Any | None = None) -> str:
    app_settings = settings or get_settings()
    provider_name = speech_provider_name(app_settings)
    if provider_name == "omniroute":
        return str(app_settings.omniroute_speech_model or app_settings.speech_model or "").strip()
    return str(app_settings.speech_model or "").strip()


def speech_configuration_status(settings: Any | None = None) -> tuple[bool, str, dict[str, str]]:
    app_settings = settings or get_settings()
    provider_name = speech_provider_name(app_settings)
    model = speech_model_from_settings(app_settings)
    if provider_name == "omniroute":
        ready = bool(app_settings.omniroute_api_key and model)
        message = (
            "Provider OmniRoute de vozes dos personagens configurado"
            if ready
            else "OMNIROUTE_API_KEY e OMNIROUTE_SPEECH_MODEL/SPEECH_MODEL são necessários"
        )
        return ready, message, {"provider": "omniroute", "model": model}
    ready = bool(app_settings.speech_api_key and model)
    message = (
        "Provider de vozes dos personagens configurado"
        if ready
        else "SPEECH_API_KEY ou SPEECH_MODEL ausente"
    )
    return ready, message, {"provider": provider_name or "openai_compatible", "model": model}
