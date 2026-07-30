from app.config.settings import (
    GROQ_TEXT_MODELS,
    NVIDIA_NIM_TEXT_MODELS,
    OLLAMA_TEXT_MODELS,
    OMNIROUTE_TEXT_MODELS,
    Settings,
)


def test_settings_defaults_to_omniroute_provider() -> None:
    settings = Settings()

    assert settings.ai_provider == "omniroute"
    assert settings.omniroute_default_model == "opencode-zen/deepseek-v4-flash"
    assert settings.omniroute_image_model == "chatgpt-web/gpt-5.5"
    assert settings.omniroute_video_model == "veo-free/veo"


def test_omniroute_text_models_are_selectable_opencode_zen_models() -> None:
    assert len(OMNIROUTE_TEXT_MODELS) == 60
    assert "opencode-zen/big-pickle" in OMNIROUTE_TEXT_MODELS
    assert "opencode-zen/deepseek-v4-flash" in OMNIROUTE_TEXT_MODELS
    assert "opencode-zen/deepseek-v4-flash-free" in OMNIROUTE_TEXT_MODELS
    assert "opencode-zen/gpt-5.6-sol" in OMNIROUTE_TEXT_MODELS
    assert "opencode-zen/claude-sonnet-4-5" in OMNIROUTE_TEXT_MODELS
    assert "opencode-zen/qwen3.6-plus" in OMNIROUTE_TEXT_MODELS


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


def test_settings_reads_openai_compatible_text_providers() -> None:
    settings = Settings(
        text_provider="groq",
        ollama_base_url="http://localhost:11434/v1",
        ollama_api_key="  ollama  ",
        ollama_default_model="llama3.1:8b",
        groq_api_key="  groq-secret  ",
        groq_base_url="https://api.groq.com/openai/v1",
        groq_default_model="llama-3.3-70b-versatile",
        nvidia_nim_api_key="  nv-secret  ",
        nvidia_nim_base_url="https://integrate.api.nvidia.com/v1",
        nvidia_nim_default_model="openai/gpt-oss-20b",
    )

    assert settings.text_provider == "groq"
    assert settings.ollama_api_key == "ollama"
    assert settings.groq_api_key == "groq-secret"
    assert settings.nvidia_nim_api_key == "nv-secret"
    assert settings.ollama_default_model == "llama3.1:8b"
    assert settings.groq_default_model == "llama-3.3-70b-versatile"
    assert settings.nvidia_nim_default_model == "openai/gpt-oss-20b"


def test_new_text_model_lists_have_initial_defaults() -> None:
    assert "llama3.1:8b" in OLLAMA_TEXT_MODELS
    assert "llama-3.3-70b-versatile" in GROQ_TEXT_MODELS
    assert "openai/gpt-oss-20b" in NVIDIA_NIM_TEXT_MODELS


def test_settings_rejects_unknown_ai_provider() -> None:
    try:
        Settings(ai_provider="unknown")
    except ValueError as exc:
        assert "AI_PROVIDER" in str(exc)
    else:
        raise AssertionError("Settings should reject unsupported providers")
