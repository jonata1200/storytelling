from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import api_keys
from app.config.api_keys import (
    format_missing_api_key_message,
    missing_api_key_messages_for_channels,
    missing_api_key_messages_for_creation_step,
    required_channels_for_creation_step,
)
from app.config.runtime_preferences import save_runtime_preferences
from app.config.settings import get_settings


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "ai_provider": "ollama_cloud",
        "text_provider": "ollama_cloud",
        "image_provider": "google_ai",
        "video_provider": "google_ai",
        "speech_provider": "elevenlabs",
        "dubbing_provider": "elevenlabs",
        "ollama_cloud_api_key": None,
        "google_ai_api_key": None,
        "elevenlabs_api_key": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_text_creation_step_reports_missing_text_provider_key() -> None:
    messages = missing_api_key_messages_for_creation_step(
        "script",
        _settings(),
    )

    assert messages == ["OLLAMA_CLOUD_API_KEY não está configurada para Ollama Cloud."]


def test_image_and_video_steps_use_google_ai_key() -> None:
    settings = _settings(ollama_cloud_api_key="ollama-secret")

    assert missing_api_key_messages_for_creation_step("storyboard", settings) == [
        "GOOGLE_AI_API_KEY não está configurada para Google AI."
    ]
    assert missing_api_key_messages_for_creation_step("video", settings) == [
        "GOOGLE_AI_API_KEY não está configurada para Google AI."
    ]


def test_dubbing_and_finalization_steps_use_elevenlabs_key() -> None:
    settings = _settings(ollama_cloud_api_key="ollama-secret", google_ai_api_key="google-secret")

    assert required_channels_for_creation_step("finalization") == ("speech",)
    assert missing_api_key_messages_for_creation_step("finalization", settings) == [
        "ELEVENLABS_API_KEY não está configurada para ElevenLabs."
    ]
    assert missing_api_key_messages_for_creation_step("dubbing", settings) == [
        "ELEVENLABS_API_KEY não está configurada para ElevenLabs."
    ]


def test_configured_keys_do_not_report_missing_messages() -> None:
    settings = _settings(
        ollama_cloud_api_key="ollama-secret",
        google_ai_api_key="google-secret",
        elevenlabs_api_key="eleven-secret",
    )

    messages = missing_api_key_messages_for_channels(
        ("text", "image", "video", "speech"),
        settings,
    )

    assert messages == []


def test_missing_key_message_points_user_to_ai_settings() -> None:
    message = format_missing_api_key_message(["GOOGLE_AI_API_KEY não está configurada."])

    assert "Configurações de IA" in message
    assert "- GOOGLE_AI_API_KEY não está configurada." in message


def test_api_key_validation_refreshes_stale_cached_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    save_runtime_preferences({"OLLAMA_CLOUD_API_KEY": ""})
    get_settings.cache_clear()
    assert not get_settings().ollama_cloud_api_key

    save_runtime_preferences({"OLLAMA_CLOUD_API_KEY": "ollama-secret"})

    assert api_keys.missing_api_key_messages_for_creation_step("ideas") == []
