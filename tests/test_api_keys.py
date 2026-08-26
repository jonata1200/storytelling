from types import SimpleNamespace

from app.config.api_keys import (
    missing_api_key_messages_for_channels,
    missing_api_key_messages_for_creation_step,
)


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "ai_provider": "ollama_cloud",
        "text_provider": "ollama_cloud",
        "video_provider": "openrouter",
        "ollama_cloud_api_key": None,
        "openrouter_api_key": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_text_step_requires_text_key() -> None:
    assert missing_api_key_messages_for_creation_step("script", _settings()) == [
        "OLLAMA_CLOUD_API_KEY não está configurada para Ollama Cloud."
    ]


def test_video_step_requires_only_video_key() -> None:
    settings = _settings(ollama_cloud_api_key="text-secret")
    assert missing_api_key_messages_for_creation_step("video", settings) == [
        "OPENROUTER_API_KEY não está configurada para OpenRouter."
    ]
    assert missing_api_key_messages_for_creation_step("storyboard", settings) == []


def test_configured_keys_are_accepted() -> None:
    settings = _settings(ollama_cloud_api_key="text", openrouter_api_key="video")
    assert missing_api_key_messages_for_channels(("text", "video"), settings) == []
