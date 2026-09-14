from app.config.provider_policy import effective_provider_for_channel
from app.config.settings import Settings


def test_settings_defaults_to_text_and_video_providers() -> None:
    settings = Settings(_env_file=None)
    assert effective_provider_for_channel(settings, "text") == "ollama_cloud"
    assert effective_provider_for_channel(settings, "image") == "meta"


def test_settings_ignores_pre_cutover_provider_environment() -> None:
    settings = Settings(
        text_provider="removed-provider",
        image_provider="removed-provider",
    )
    assert settings.text_provider == "ollama_cloud"
    assert settings.image_provider == "meta"
