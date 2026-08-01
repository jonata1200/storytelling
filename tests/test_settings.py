from app.config.provider_policy import effective_provider_for_channel
from app.config.settings import (
    ELEVENLABS_SPEECH_MODELS,
    GOOGLE_AI_IMAGE_MODELS,
    GOOGLE_AI_VIDEO_MODELS,
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
    assert settings.google_ai_base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert settings.google_ai_image_model == "gemini-3.1-flash-image"
    assert settings.google_ai_video_model == "veo-3.1-generate-preview"
    assert settings.speech_provider == "elevenlabs"
    assert settings.elevenlabs_speech_model == "eleven_multilingual_v2"
    assert settings.dubbing_provider == "elevenlabs"
    assert settings.dubbing_source_lang == "pt"
    assert settings.dubbing_target_lang == "en"


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


def test_settings_reads_google_ai_media_provider() -> None:
    settings = Settings(
        image_provider="google_ai",
        video_provider="google_ai",
        google_ai_api_key="  google-secret  ",
        google_ai_image_model="gemini-3-pro-image",
        google_ai_image_size="2K",
        google_ai_video_model="veo-3.1-fast-generate-preview",
        google_ai_video_default_duration_seconds=6,
        google_ai_video_poll_interval_seconds=2,
        google_ai_video_poll_timeout_seconds=30,
    )

    assert settings.image_provider == "google_ai"
    assert settings.video_provider == "google_ai"
    assert settings.google_ai_api_key == "google-secret"
    assert settings.google_ai_image_model == "gemini-3-pro-image"
    assert settings.google_ai_image_size == "2K"
    assert settings.google_ai_video_model == "veo-3.1-fast-generate-preview"
    assert settings.google_ai_video_default_duration_seconds == 6
    assert settings.google_ai_video_poll_interval_seconds == 2
    assert settings.google_ai_video_poll_timeout_seconds == 30


def test_settings_reads_elevenlabs_voice_and_dubbing_provider() -> None:
    settings = Settings(
        speech_provider="elevenlabs",
        elevenlabs_api_key="  eleven-secret  ",
        elevenlabs_voice_id="voice-1",
        elevenlabs_speech_model="eleven_flash_v2_5",
        elevenlabs_output_format="mp3_44100_128",
        dubbing_provider="elevenlabs",
        dubbing_source_lang="pt",
        dubbing_target_lang="es",
        dubbing_poll_interval_seconds=2,
        dubbing_poll_timeout_seconds=30,
    )

    assert settings.speech_provider == "elevenlabs"
    assert settings.elevenlabs_api_key == "eleven-secret"
    assert settings.elevenlabs_voice_id == "voice-1"
    assert settings.elevenlabs_speech_model == "eleven_flash_v2_5"
    assert settings.elevenlabs_output_format == "mp3_44100_128"
    assert settings.dubbing_provider == "elevenlabs"
    assert settings.dubbing_source_lang == "pt"
    assert settings.dubbing_target_lang == "es"
    assert settings.dubbing_poll_interval_seconds == 2
    assert settings.dubbing_poll_timeout_seconds == 30


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
    assert GOOGLE_AI_IMAGE_MODELS == (
        "gemini-3.1-flash-image",
        "gemini-3.1-flash-lite-image",
        "gemini-3-pro-image",
        "gemini-2.5-flash-image",
    )
    assert GOOGLE_AI_VIDEO_MODELS == (
        "veo-3.1-generate-preview",
        "veo-3.1-fast-generate-preview",
        "veo-3.1-lite-generate-preview",
        "veo-3.0-generate-001",
        "veo-3.0-fast-generate-001",
    )
    assert ELEVENLABS_SPEECH_MODELS == (
        "eleven_multilingual_v2",
        "eleven_turbo_v2_5",
        "eleven_flash_v2_5",
        "eleven_v3",
    )


def test_settings_rejects_unknown_ai_provider() -> None:
    try:
        Settings(ai_provider="unknown")
    except ValueError as exc:
        assert "AI_PROVIDER" in str(exc)
    else:
        raise AssertionError("Settings should reject unsupported providers")
