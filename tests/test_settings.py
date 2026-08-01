from app.config.provider_policy import effective_provider_for_channel
from app.config.settings import (
    NVIDIA_NIM_TEXT_MODELS,
    OLLAMA_CLOUD_TEXT_MODELS,
    Settings,
)


def test_settings_defaults_to_new_ai_providers() -> None:
    settings = Settings()

    assert settings.ai_provider == "nvidia_nim"
    assert effective_provider_for_channel(settings, "text") == "nvidia_nim"
    assert effective_provider_for_channel(settings, "image") == "veo_ai_free"
    assert effective_provider_for_channel(settings, "video") == "veo_ai_free"
    assert settings.nvidia_nim_default_model == "z-ai/glm-5.2"
    assert settings.veo_ai_free_image_model == "veo-ai-free/image"
    assert settings.veo_ai_free_video_model == "veo-ai-free/video"


def test_settings_maps_legacy_omniroute_provider_to_new_default() -> None:
    settings = Settings(
        ai_provider="omniroute",
    )

    assert settings.ai_provider == "nvidia_nim"


def test_settings_reads_nvidia_nim_text_provider() -> None:
    settings = Settings(
        text_provider="nvidia_nim",
        nvidia_nim_api_key="  nv-secret  ",
        nvidia_nim_base_url="https://integrate.api.nvidia.com/v1",
        nvidia_nim_default_model="z-ai/glm-5.2",
    )

    assert settings.text_provider == "nvidia_nim"
    assert settings.nvidia_nim_api_key == "nv-secret"
    assert settings.nvidia_nim_default_model == "z-ai/glm-5.2"


def test_settings_reads_ollama_cloud_text_provider() -> None:
    settings = Settings(
        text_provider="ollama_cloud",
        ollama_cloud_api_key="  ollama-secret  ",
        ollama_cloud_base_url="https://ollama.com/api",
        ollama_cloud_default_model="gpt-oss:120b",
    )

    assert settings.text_provider == "ollama_cloud"
    assert settings.ollama_cloud_api_key == "ollama-secret"
    assert settings.ollama_cloud_default_model == "gpt-oss:120b"


def test_new_text_model_lists_have_initial_defaults() -> None:
    assert NVIDIA_NIM_TEXT_MODELS == (
        "deepseek-ai/deepseek-v4-flash",
        "deepseek-ai/deepseek-v4-pro",
        "google/gemma-4-31b-it",
        "meta/llama-3.1-70b-instruct",
        "meta/llama-3.3-70b-instruct",
        "minimaxai/minimax-m3",
        "mistralai/mistral-medium-3.5-128b",
        "moonshotai/kimi-k2.6",
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "nvidia/nemotron-3-super-120b-a12b",
        "nvidia/nemotron-3-ultra-550b-a55b",
        "qwen/qwen3-next-80b-a3b-instruct",
        "stepfun-ai/step-3.7-flash",
        "z-ai/glm-5.2",
    )
    assert OLLAMA_CLOUD_TEXT_MODELS == (
        "gpt-oss:120b",
        "gpt-oss:20b",
    )


def test_settings_rejects_unknown_ai_provider() -> None:
    try:
        Settings(ai_provider="unknown")
    except ValueError as exc:
        assert "AI_PROVIDER" in str(exc)
    else:
        raise AssertionError("Settings should reject unsupported providers")
