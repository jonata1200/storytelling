import pytest

from app.config.provider_policy import (
    effective_provider_for_channel,
    ensure_provider_api_key,
    normalize_provider_name,
    validate_model_name,
)
from app.config.settings import Settings


def test_validate_model_name_blocks_free_and_mock_models() -> None:
    with pytest.raises(ValueError, match="free"):
        validate_model_name("google/gemini-flash:free", provider="omniroute")

    with pytest.raises(ValueError, match="mock"):
        validate_model_name("mock-video", provider="omniroute")


def test_effective_provider_for_channel_uses_media_override() -> None:
    settings = Settings(ai_provider="omniroute", image_provider="omniroute")

    assert effective_provider_for_channel(settings, "text") == "omniroute"
    assert effective_provider_for_channel(settings, "image") == "omniroute"


def test_ensure_provider_api_key_keeps_omniroute_prefix_flexible() -> None:
    assert ensure_provider_api_key("  omni-secret  ", "omniroute") == "omni-secret"


def test_normalize_provider_name_rejects_mock_provider() -> None:
    with pytest.raises(ValueError, match="Provider"):
        normalize_provider_name("mock", "Provider")
