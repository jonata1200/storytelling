from app.config.provider_policy import effective_provider_for_channel
from app.config.settings import (
    GROQ_TEXT_MODELS,
    NVIDIA_NIM_TEXT_MODELS,
    OLLAMA_TEXT_MODELS,
    Settings,
)


def test_settings_defaults_to_new_ai_providers() -> None:
    settings = Settings()

    assert settings.ai_provider == "ollama"
    assert effective_provider_for_channel(settings, "text") == "ollama"
    assert effective_provider_for_channel(settings, "image") == "veo_ai_free"
    assert effective_provider_for_channel(settings, "video") == "veo_ai_free"
    assert settings.ollama_default_model == "llama3.1:8b"
    assert settings.veo_ai_free_image_model == "veo-ai-free/image"
    assert settings.veo_ai_free_video_model == "veo-ai-free/video"


def test_settings_maps_legacy_omniroute_provider_to_new_default() -> None:
    settings = Settings(
        ai_provider="omniroute",
    )

    assert settings.ai_provider == "ollama"


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
