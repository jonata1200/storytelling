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
        validate_model_name("google/gemini-flash:free", provider="omniroute")

    with pytest.raises(ValueError, match="mock"):
        validate_model_name("mock-video", provider="omniroute")


def test_effective_provider_for_channel_uses_media_override() -> None:
    settings = Settings(
        ai_provider="omniroute",
        image_provider="omniroute",
    )

    assert effective_provider_for_channel(settings, "text") == "omniroute"
    assert effective_provider_for_channel(settings, "image") == "omniroute"


def test_validate_model_name_allows_omniroute_opencode_zen_model() -> None:
    assert (
        validate_model_name("opencode-zen/deepseek-v4-flash", provider="omniroute")
        == "opencode-zen/deepseek-v4-flash"
    )


def test_ensure_provider_api_key_keeps_omniroute_prefix_flexible() -> None:
    assert ensure_provider_api_key("  omni-secret  ", "omniroute") == "omni-secret"


def test_normalize_provider_name_rejects_mock_provider() -> None:
    with pytest.raises(ValueError, match="Provider"):
        normalize_provider_name("mock", "Provider")


def test_provider_policy_supports_new_text_providers() -> None:
    settings = Settings(
        text_provider="ollama",
        ollama_base_url="http://localhost:11434/v1",
        ollama_default_model="llama3.1:8b",
    )

    assert "ollama" in SUPPORTED_AI_PROVIDERS
    assert "groq" in SUPPORTED_AI_PROVIDERS
    assert "nvidia_nim" in SUPPORTED_AI_PROVIDERS
    assert effective_provider_for_channel(settings, "text") == "ollama"
    assert provider_display_name("nvidia_nim") == "NVIDIA NIM"
    assert provider_base_url(settings, "ollama") == "http://localhost:11434/v1"
    assert provider_model(settings, "ollama", "text") == "llama3.1:8b"
    assert provider_requires_api_key(settings, "ollama") is False


def test_nvidia_nim_requires_key_only_for_hosted_endpoint() -> None:
    hosted = Settings(nvidia_nim_base_url="https://integrate.api.nvidia.com/v1")
    local = Settings(nvidia_nim_base_url="http://localhost:8000/v1")

    assert provider_requires_api_key(hosted, "nvidia_nim") is True
    assert provider_requires_api_key(local, "nvidia_nim") is False
