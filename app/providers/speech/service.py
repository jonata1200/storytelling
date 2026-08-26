from typing import Any

from app.providers.speech.types import SpeechProvider


def speech_provider_from_settings(settings: Any | None = None) -> SpeechProvider | None:
    """Return None instead of raising, consistent with other speech helpers."""
    return None


def speech_provider_name(settings: Any | None = None) -> str:
    return ""


def speech_model_from_settings(settings: Any | None = None) -> str:
    return ""


def speech_configuration_status(settings: Any | None = None) -> tuple[bool, str, dict[str, str]]:
    return False, "Provider de voz nao esta configurado.", {"provider": "", "model": ""}
