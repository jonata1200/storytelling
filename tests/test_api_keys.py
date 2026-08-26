from types import SimpleNamespace

from app.config.api_keys import (
    missing_api_key_messages_for_channels,
    missing_api_key_messages_for_creation_step,
)


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "text_provider": "ollama_cloud",
        "image_provider": "meta",
        "video_provider": "vibes",
        "ollama_cloud_integration_mode": "api",
        "meta_image_integration_mode": "browser",
        "vibes_integration_mode": "browser",
        "ollama_cloud_api_key": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_text_step_requires_text_key() -> None:
    assert missing_api_key_messages_for_creation_step("script", _settings()) == [
        "OLLAMA_API_KEY não está configurada para Ollama Cloud."
    ]


def test_browser_video_step_does_not_require_api_key() -> None:
    settings = _settings(ollama_cloud_api_key="fake-text-secret")
    assert missing_api_key_messages_for_creation_step("video", settings) == []
    assert missing_api_key_messages_for_creation_step("storyboard", settings) == []


def test_configured_keys_are_accepted() -> None:
    settings = _settings(ollama_cloud_api_key="text")
    assert missing_api_key_messages_for_channels(("text", "video"), settings) == []
