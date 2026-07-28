from app.config.settings import Settings


def test_settings_defaults_to_omniroute_provider() -> None:
    settings = Settings()

    assert settings.ai_provider == "omniroute"


def test_settings_reads_omniroute_configuration() -> None:
    settings = Settings(
        ai_provider="omniroute",
        omniroute_api_key="  omni-secret  ",
        omniroute_base_url="https://omnirouters.com/v1",
        omniroute_default_model="vendor/text-model",
        omniroute_image_model="vendor/image-model",
        omniroute_video_model="vendor/video-model",
        omniroute_speech_model="vendor/speech-model",
    )

    assert settings.ai_provider == "omniroute"
    assert settings.omniroute_api_key == "omni-secret"
    assert settings.omniroute_base_url == "https://omnirouters.com/v1"
    assert settings.omniroute_default_model == "vendor/text-model"
    assert settings.omniroute_image_model == "vendor/image-model"
    assert settings.omniroute_video_model == "vendor/video-model"
    assert settings.omniroute_speech_model == "vendor/speech-model"


def test_settings_rejects_unknown_ai_provider() -> None:
    try:
        Settings(ai_provider="unknown")
    except ValueError as exc:
        assert "AI_PROVIDER" in str(exc)
    else:
        raise AssertionError("Settings should reject unsupported providers")
