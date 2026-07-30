import pytest

from app.config.provider_policy import (
    effective_provider_for_channel,
    ensure_provider_api_key,
    normalize_provider_name,
    provider_api_key,
    provider_base_url,
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
        text_provider="opencode",
        image_provider="omniroute",
    )

    assert effective_provider_for_channel(settings, "text") == "opencode"
    assert effective_provider_for_channel(settings, "image") == "omniroute"


def test_opencode_uses_omniroute_gateway_configuration_as_fallback() -> None:
    settings = Settings(
        omniroute_api_key="omni-secret",
        omniroute_base_url="https://omnirouters.com/v1",
        opencode_api_key=None,
        opencode_base_url="",
    )

    assert provider_api_key(settings, "opencode") == "omni-secret"
    assert provider_base_url(settings, "opencode") == "https://omnirouters.com/v1"


def test_validate_model_name_allows_opencode_dash_free_model() -> None:
    assert (
        validate_model_name("oc/deepseek-v4-flash-free", provider="opencode")
        == "oc/deepseek-v4-flash-free"
    )


def test_ensure_provider_api_key_keeps_omniroute_prefix_flexible() -> None:
    assert ensure_provider_api_key("  omni-secret  ", "omniroute") == "omni-secret"


def test_normalize_provider_name_rejects_mock_provider() -> None:
    with pytest.raises(ValueError, match="Provider"):
        normalize_provider_name("mock", "Provider")
