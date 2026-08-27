from types import SimpleNamespace

from app.config.api_keys import (
    missing_api_key_messages_for_channels,
    missing_api_key_messages_for_creation_step,
)


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "text_provider": "meta",
        "image_provider": "meta",
        "video_provider": "vibes",
        "meta_integration_mode": "api",
        "meta_image_integration_mode": "api",
        "vibes_integration_mode": "browser",
        "meta_api_key": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_text_step_requires_text_key() -> None:
    assert missing_api_key_messages_for_creation_step("script", _settings()) == [
        "META_API_KEY não está configurada para Meta."
    ]


def test_browser_video_step_does_not_require_api_key() -> None:
    settings = _settings(meta_api_key="text-secret")
    assert missing_api_key_messages_for_creation_step("video", settings) == []
    assert missing_api_key_messages_for_creation_step("storyboard", settings) == []


def test_configured_keys_are_accepted() -> None:
    settings = _settings(meta_api_key="text")
    assert missing_api_key_messages_for_channels(("text", "video"), settings) == []
