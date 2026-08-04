from typing import Any

from app.config.settings import get_settings
from app.providers.speech.elevenlabs import ElevenLabsSpeechProvider
from app.providers.speech.types import SpeechProvider


def speech_provider_from_settings() -> SpeechProvider:
    provider_name = speech_provider_name()
    if provider_name == "elevenlabs":
        return ElevenLabsSpeechProvider()
    if provider_name == "mock":
        raise ValueError("Provider mock de voz está bloqueado no fluxo de audio real.")
    raise ValueError("Provider de voz não suportado. Use ElevenLabs.")


def speech_provider_name(settings: Any | None = None) -> str:
    app_settings = settings or get_settings()
    return str(app_settings.speech_provider or "").strip().lower()


def speech_model_from_settings(settings: Any | None = None) -> str:
    app_settings = settings or get_settings()
    provider_name = speech_provider_name(app_settings)
    if provider_name == "elevenlabs":
        return str(app_settings.elevenlabs_speech_model or "").strip()
    return ""


def speech_configuration_status(settings: Any | None = None) -> tuple[bool, str, dict[str, str]]:
    app_settings = settings or get_settings()
    provider_name = speech_provider_name(app_settings)
    model = speech_model_from_settings(app_settings)
    if provider_name == "elevenlabs":
        ready = bool(app_settings.elevenlabs_api_key and app_settings.elevenlabs_voice_id and model)
        message = (
            "Provider ElevenLabs de vozes e dublagem configurado"
            if ready
            else "ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID e ELEVENLABS_SPEECH_MODEL são necessários"
        )
        return ready, message, {"provider": "elevenlabs", "model": model}
    return False, "Provider de voz não suportado. Use ElevenLabs.", {
        "provider": provider_name or "elevenlabs",
        "model": model,
    }
