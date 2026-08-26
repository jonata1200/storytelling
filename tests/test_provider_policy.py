import pytest

from app.config.provider_policy import (
    effective_provider_for_channel,
    ensure_provider_api_key,
    provider_model,
    validate_model_name,
)
from app.config.settings import Settings


def test_validate_model_name_blocks_free_and_mock_models() -> None:
    with pytest.raises(ValueError, match="free"):
        validate_model_name("video:free", provider="vibes")
    with pytest.raises(ValueError, match="mock"):
        validate_model_name("mock-media", provider="vibes")


def test_provider_policy_resolves_all_channels() -> None:
    settings = Settings(_env_file=None)
    assert effective_provider_for_channel(settings, "text") == "ollama_cloud"
    assert effective_provider_for_channel(settings, "image") == "meta"
    assert effective_provider_for_channel(settings, "video") == "vibes"
    assert provider_model(settings, "vibes", "video") == settings.vibes_video_model


def test_ensure_provider_api_key_trims_secret() -> None:
    assert ensure_provider_api_key("  secret  ", "ollama_cloud") == "secret"
