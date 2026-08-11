import pytest

from app.config.provider_policy import (
    SUPPORTED_AI_PROVIDERS,
    effective_provider_for_channel,
    ensure_provider_api_key,
    normalize_provider_name,
    provider_base_url,
    provider_display_name,
    provider_model,
    provider_requires_api_key,
    validate_model_name,
)
from app.config.settings import Settings


def test_validate_model_name_blocks_free_and_mock_models() -> None:
    with pytest.raises(ValueError, match="free"):
        validate_model_name("google/gemini-flash:free", provider="google_ai")

    with pytest.raises(ValueError, match="mock"):
        validate_model_name("mock-video", provider="google_ai")


def test_effective_provider_for_channel_uses_media_override() -> None:
    settings = Settings(
        ai_provider="ollama_cloud",
        image_provider="google_ai",
    )

    assert effective_provider_for_channel(settings, "image") == "google_ai"


def test_ensure_provider_api_key_trims_secret() -> None:
    assert ensure_provider_api_key("  provider-secret  ", "google_ai") == "provider-secret"


def test_normalize_provider_name_rejects_mock_provider() -> None:
    with pytest.raises(ValueError, match="Provider"):
        normalize_provider_name("mock", "Provider")


def test_provider_policy_supports_new_text_providers() -> None:
    settings = Settings(
        text_provider="ollama_cloud",
        ollama_cloud_base_url="https://ollama.com/api",
        ollama_cloud_default_model="gemma4:cloud",
    )

    assert "ollama" not in SUPPORTED_AI_PROVIDERS
    assert "groq" not in SUPPORTED_AI_PROVIDERS
    assert "ollama_cloud" in SUPPORTED_AI_PROVIDERS
    assert effective_provider_for_channel(settings, "text") == "ollama_cloud"
    assert provider_display_name("ollama_cloud") == "Ollama Cloud"
    assert provider_base_url(settings, "ollama_cloud") == "https://ollama.com/api"
    assert provider_model(settings, "ollama_cloud", "text") == "gemma4:cloud"
    assert provider_requires_api_key(settings, "ollama_cloud") is True


def test_provider_policy_supports_google_ai_media_provider() -> None:
    settings = Settings(
        image_provider="google_ai",
        video_provider="google_ai",
        google_ai_api_key="google-secret",
        google_ai_base_url="https://generativelanguage.googleapis.com/v1beta",
        google_ai_image_model="gemini-3.1-flash-lite-image",
        google_ai_video_model="veo-3.1-generate-preview",
    )

    assert "google_ai" in SUPPORTED_AI_PROVIDERS
    assert effective_provider_for_channel(settings, "image") == "google_ai"
    assert effective_provider_for_channel(settings, "video") == "google_ai"
    assert provider_display_name("google_ai") == "Google AI"
    assert provider_base_url(settings, "google_ai") == (
        "https://generativelanguage.googleapis.com/v1beta"
    )
    assert provider_model(settings, "google_ai", "image") == "gemini-3.1-flash-lite-image"
    assert provider_model(settings, "google_ai", "video") == "veo-3.1-generate-preview"
    assert provider_requires_api_key(settings, "google_ai") is True


def test_provider_requires_api_key_distinguishes_mock_and_unknown_providers() -> None:
    settings = Settings(
        text_provider="ollama_cloud",
        ollama_cloud_api_key="ollama-secret",
        google_ai_api_key="google-secret",
        elevenlabs_api_key="eleven-secret",
    )

    assert provider_requires_api_key(settings, "ollama_cloud") is True
    assert provider_requires_api_key(settings, "google_ai") is True
    assert provider_requires_api_key(settings, "elevenlabs") is True
    assert provider_requires_api_key(settings, "mock") is False
    assert provider_requires_api_key(settings, "mock-video") is False
    assert provider_requires_api_key(settings, "unknown_provider") is False
    assert provider_requires_api_key(settings, "") is False
