from app.config.provider_policy import effective_provider_for_channel
from app.config.settings import (
    ELEVENLABS_SPEECH_MODELS,
    GOOGLE_AI_IMAGE_MODELS,
    GOOGLE_AI_VIDEO_MODELS,
    OLLAMA_CLOUD_TEXT_MODELS,
    Settings,
)


def test_settings_defaults_to_new_ai_providers() -> None:
    settings = Settings()

    assert settings.ai_provider == "ollama_cloud"
    assert effective_provider_for_channel(settings, "text") == "ollama_cloud"
    assert effective_provider_for_channel(settings, "image") == "google_ai"
    assert effective_provider_for_channel(settings, "video") == "google_ai"
    assert settings.google_ai_base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert settings.google_ai_image_model == "gemini-3.1-flash-lite-image"
    assert settings.google_ai_video_model == "veo-3.1-lite-generate-preview"
    assert settings.speech_provider == "elevenlabs"
    assert settings.elevenlabs_speech_model == "eleven_multilingual_v2"
    assert settings.dubbing_provider == "elevenlabs"
    assert settings.dubbing_source_lang == "pt"
    assert settings.dubbing_target_lang == "en"


def test_settings_reads_ollama_cloud_text_provider() -> None:
    settings = Settings(
        text_provider="ollama_cloud",
        ollama_cloud_api_key="  ollama-secret  ",
        ollama_cloud_base_url="https://ollama.com/api",
        ollama_cloud_default_model="minimax-m2.7:cloud",
    )

    assert settings.text_provider == "ollama_cloud"
    assert settings.ollama_cloud_api_key == "ollama-secret"
    assert settings.ollama_cloud_default_model == "minimax-m2.7:cloud"


def test_settings_replaces_removed_ollama_cloud_model_with_default() -> None:
    settings = Settings(ollama_cloud_default_model="gpt-oss:120b")

    assert settings.ollama_cloud_default_model == "deepseek-v4-flash:cloud"


def test_settings_replaces_removed_google_ai_models_with_defaults() -> None:
    settings = Settings(
        google_ai_image_model="gemini-3.1-flash-image",
        google_ai_video_model="veo-3.1-generate-preview",
    )

    assert settings.google_ai_image_model == "gemini-3.1-flash-lite-image"
    assert settings.google_ai_video_model == "veo-3.1-lite-generate-preview"


def test_settings_reads_google_ai_media_provider() -> None:
    settings = Settings(
        image_provider="google_ai",
        video_provider="google_ai",
        google_ai_api_key="  google-secret  ",
        google_ai_image_model="gemini-3.1-flash-lite-image",
        google_ai_image_size="2K",
        google_ai_video_model="veo-3.1-lite-generate-preview",
        google_ai_video_default_duration_seconds=6,
        google_ai_video_poll_interval_seconds=2,
        google_ai_video_poll_timeout_seconds=30,
    )

    assert settings.image_provider == "google_ai"
    assert settings.video_provider == "google_ai"
    assert settings.google_ai_api_key == "google-secret"
    assert settings.google_ai_image_model == "gemini-3.1-flash-lite-image"
    assert settings.google_ai_image_size == "2K"
    assert settings.google_ai_video_model == "veo-3.1-lite-generate-preview"
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
    assert OLLAMA_CLOUD_TEXT_MODELS == (
        "deepseek-v4-flash:cloud",
        "gemma4:cloud",
        "minimax-m2.7:cloud",
        "mistral-large-3:675b-cloud",
        "nemotron-3-nano:30b-cloud",
        "nemotron-3-super:cloud",
    )
    assert GOOGLE_AI_IMAGE_MODELS == (
        "gemini-3.1-flash-lite-image",
    )
    assert GOOGLE_AI_VIDEO_MODELS == (
        "veo-3.1-lite-generate-preview",
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
