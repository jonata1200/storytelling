from app.config.settings import Settings


def test_settings_rejects_invalid_openrouter_api_key() -> None:
    settings = Settings(openrouter_api_key="JKl1464&*")

    assert settings.openrouter_api_key is None


def test_settings_strips_valid_openrouter_api_key() -> None:
    settings = Settings(openrouter_api_key="  sk-or-v1-test  ")

    assert settings.openrouter_api_key == "sk-or-v1-test"
