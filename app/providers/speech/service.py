from app.config.settings import get_settings
from app.providers.speech.openai_compatible import OpenAICompatibleSpeechProvider
from app.providers.speech.types import SpeechProvider


def speech_provider_from_settings() -> SpeechProvider:
    provider_name = get_settings().speech_provider.strip().lower()
    if provider_name in {"openai_compatible", "openai-compatible"}:
        return OpenAICompatibleSpeechProvider()
    if provider_name == "mock":
        raise ValueError("Provider mock de voz esta bloqueado no fluxo de narracao final.")
    raise ValueError(f"Provider de voz nao suportado: {provider_name}")
