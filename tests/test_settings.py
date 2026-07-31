from app.config.provider_policy import effective_provider_for_channel
from app.config.settings import (
    NVIDIA_NIM_TEXT_MODELS,
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


def test_new_text_model_lists_have_initial_defaults() -> None:
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


def test_settings_rejects_unknown_ai_provider() -> None:
    try:
        Settings(ai_provider="unknown")
    except ValueError as exc:
        assert "AI_PROVIDER" in str(exc)
    else:
        raise AssertionError("Settings should reject unsupported providers")
