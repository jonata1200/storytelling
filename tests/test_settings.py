import pytest

from app.config.provider_policy import effective_provider_for_channel
from app.config.settings import LOCKED_OLLAMA_CLOUD_TEXT_MODEL, OLLAMA_CLOUD_TEXT_MODELS, Settings


def test_settings_defaults_to_text_and_video_providers() -> None:
    settings = Settings(_env_file=None)
    assert effective_provider_for_channel(settings, "text") == "ollama_cloud"
    assert effective_provider_for_channel(settings, "video") == "openrouter"


def test_settings_normalizes_provider_keys() -> None:
    settings = Settings(
        ollama_cloud_api_key="  ollama-secret  ",
        openrouter_api_key="  or-secret  ",
    )
    assert settings.ollama_cloud_api_key == "ollama-secret"
    assert settings.openrouter_api_key == "or-secret"


def test_settings_replaces_removed_ollama_model_with_default() -> None:
    assert (
        Settings(ollama_cloud_default_model="removed-model").ollama_cloud_default_model
        == LOCKED_OLLAMA_CLOUD_TEXT_MODEL
    )


def test_text_model_catalog_is_sorted() -> None:
    assert OLLAMA_CLOUD_TEXT_MODELS == tuple(sorted(OLLAMA_CLOUD_TEXT_MODELS))


@pytest.mark.parametrize("model", OLLAMA_CLOUD_TEXT_MODELS)
def test_settings_accepts_supported_ollama_model(model: str) -> None:
    assert Settings(ollama_cloud_default_model=model).ollama_cloud_default_model == model


def test_settings_rejects_unknown_ai_provider() -> None:
    with pytest.raises(ValueError, match="AI_PROVIDER"):
        Settings(ai_provider="unknown")
