from app.config.provider_policy import effective_provider_for_channel
from app.config.settings import (
    GROQ_TEXT_MODELS,
    NVIDIA_NIM_IMAGE_MODELS,
    NVIDIA_NIM_TEXT_MODELS,
    OLLAMA_TEXT_MODELS,
    Settings,
)


def test_settings_defaults_to_new_ai_providers() -> None:
    settings = Settings()

    assert settings.ai_provider == "ollama"
    assert effective_provider_for_channel(settings, "text") == "ollama"
    assert effective_provider_for_channel(settings, "image") == "nvidia_nim"
    assert effective_provider_for_channel(settings, "video") == "veo_ai_free"
    assert settings.ollama_default_model == "kimi-k3:cloud"
    assert settings.nvidia_nim_image_base_url == "https://ai.api.nvidia.com/v1/genai"
    assert settings.nvidia_nim_image_model == "qwen/qwen-image"
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
        ollama_default_model="gpt-oss:120b-cloud",
        groq_api_key="  groq-secret  ",
        groq_base_url="https://api.groq.com/openai/v1",
        groq_default_model="openai/gpt-oss-120b",
        nvidia_nim_api_key="  nv-secret  ",
        nvidia_nim_base_url="https://integrate.api.nvidia.com/v1",
        nvidia_nim_default_model="z-ai/glm-5.2",
    )

    assert settings.text_provider == "groq"
    assert settings.ollama_api_key == "ollama"
    assert settings.groq_api_key == "groq-secret"
    assert settings.nvidia_nim_api_key == "nv-secret"
    assert settings.ollama_default_model == "gpt-oss:120b-cloud"
    assert settings.groq_default_model == "openai/gpt-oss-120b"
    assert settings.nvidia_nim_default_model == "z-ai/glm-5.2"


def test_new_text_model_lists_have_initial_defaults() -> None:
    assert OLLAMA_TEXT_MODELS == (
        "kimi-k3:cloud",
        "glm-5.2:cloud",
        "nemotron-3-ultra:cloud",
        "deepseek-v4-pro:cloud",
        "minimax-m3:cloud",
        "kimi-k2.7-code:cloud",
        "glm-5.1:cloud",
        "qwen3.5:397b-cloud",
        "nemotron-3-super:cloud",
        "gpt-oss:120b-cloud",
    )
    assert GROQ_TEXT_MODELS == (
        "openai/gpt-oss-120b",
        "qwen/qwen3.6-27b",
        "minimaxai/minimax-m2.7",
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-20b",
        "llama-3.1-8b-instant",
    )
    assert NVIDIA_NIM_TEXT_MODELS == (
        "z-ai/glm-5.2",
        "nvidia/nemotron-3-ultra-550b-a55b",
        "deepseek-ai/deepseek-v4-pro",
        "moonshotai/kimi-k2.6",
        "minimaxai/minimax-m3",
        "qwen/qwen3.5-397b-a17b",
        "mistralai/mistral-large-3-675b-instruct-2512",
        "nvidia/nemotron-3-super-120b-a12b",
        "mistralai/mistral-medium-3.5-128b",
        "minimaxai/minimax-m2.7",
    )
    assert NVIDIA_NIM_IMAGE_MODELS == (
        "qwen/qwen-image",
        "black-forest-labs/flux.1-schnell",
        "black-forest-labs/flux.1-dev",
        "stabilityai/stable-diffusion-3.5-large",
    )


def test_settings_rejects_unknown_ai_provider() -> None:
    try:
        Settings(ai_provider="unknown")
    except ValueError as exc:
        assert "AI_PROVIDER" in str(exc)
    else:
        raise AssertionError("Settings should reject unsupported providers")
