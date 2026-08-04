from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.provider_policy import normalize_api_key, normalize_provider_name


def normalize_omniroute_api_key(value: str | None) -> str | None:
    return normalize_api_key(value, "omniroute")


OMNIROUTE_TEXT_MODELS = (
    "opencode-zen/big-pickle",
    "opencode-zen/deepseek-v4-flash",
    "opencode-zen/deepseek-v4-flash-free",
    "opencode-zen/deepseek-v4-pro",
    "opencode-zen/gpt-5",
    "opencode-zen/gpt-5-nano",
    "opencode-zen/gpt-5-codex",
    "opencode-zen/gpt-5.1",
    "opencode-zen/gpt-5.1-codex",
    "opencode-zen/gpt-5.1-codex-max",
    "opencode-zen/gpt-5.1-codex-mini",
    "opencode-zen/gpt-5.2",
    "opencode-zen/gpt-5.2-codex",
    "opencode-zen/gpt-5.3-codex",
    "opencode-zen/gpt-5.3-codex-spark",
    "opencode-zen/gpt-5.4",
    "opencode-zen/gpt-5.4-pro",
    "opencode-zen/gpt-5.4-mini",
    "opencode-zen/gpt-5.4-nano",
    "opencode-zen/gpt-5.5",
    "opencode-zen/gpt-5.5-pro",
    "opencode-zen/gpt-5.6-sol",
    "opencode-zen/gpt-5.6-terra",
    "opencode-zen/gpt-5.6-luna",
    "opencode-zen/claude-fable-5",
    "opencode-zen/claude-haiku-4-5",
    "opencode-zen/claude-sonnet-4",
    "opencode-zen/claude-sonnet-4-5",
    "opencode-zen/claude-sonnet-4-6",
    "opencode-zen/claude-sonnet-5",
    "opencode-zen/claude-opus-4-1",
    "opencode-zen/claude-opus-4-5",
    "opencode-zen/claude-opus-4-6",
    "opencode-zen/claude-opus-4-7",
    "opencode-zen/claude-opus-4-8",
    "opencode-zen/claude-opus-5",
    "opencode-zen/gemini-3-flash",
    "opencode-zen/gemini-3.1-pro",
    "opencode-zen/gemini-3.5-flash",
    "opencode-zen/gemini-3.5-flash-lite",
    "opencode-zen/gemini-3.6-flash",
    "opencode-zen/grok-build-0.1",
    "opencode-zen/grok-4.5",
    "opencode-zen/glm-5",
    "opencode-zen/glm-5.1",
    "opencode-zen/glm-5.2",
    "opencode-zen/minimax-m3",
    "opencode-zen/minimax-m2.7",
    "opencode-zen/minimax-m2.5",
    "opencode-zen/mimo-v2.5-free",
    "opencode-zen/kimi-k2.5",
    "opencode-zen/kimi-k2.6",
    "opencode-zen/kimi-k2.7-code",
    "opencode-zen/kimi-k3",
    "opencode-zen/qwen3.6-plus",
    "opencode-zen/qwen3.5-plus",
    "opencode-zen/ling-3.0-flash-free",
    "opencode-zen/nemotron-3-ultra-free",
    "opencode-zen/north-mini-code-free",
    "opencode-zen/laguna-s-2.1-free",
)

OLLAMA_CLOUD_TEXT_MODELS = (
    "deepseek-v4-flash:cloud",
    "gemma4:cloud",
    "minimax-m2.7:cloud",
    "mistral-large-3:675b-cloud",
    "nemotron-3-nano:30b-cloud",
    "nemotron-3-super:cloud",
)

GOOGLE_AI_IMAGE_MODELS = (
    "gemini-3.1-flash-lite-image",
)

GOOGLE_AI_VIDEO_MODELS = (
    "veo-3.1-fast-generate-preview",
)

ELEVENLABS_SPEECH_MODELS = (
    "eleven_multilingual_v2",
    "eleven_turbo_v2_5",
    "eleven_flash_v2_5",
    "eleven_v3",
)


class Settings(BaseSettings):
    app_name: str = "Storytelling"
    app_env: str = "local"
    app_debug: bool = True
    app_secret_key: str = Field(default="change-me-in-development", repr=False)

    database_url: str = "postgresql+asyncpg://storytelling:storytelling@localhost:5432/storytelling"
    redis_url: str = "redis://localhost:6379/0"

    storage_backend: str = "local"
    local_storage_path: Path = Path("./storage")
    max_upload_bytes: int = 25 * 1024 * 1024
    max_generated_asset_bytes: int = 750 * 1024 * 1024
    allow_user_registration: bool = True
    single_user_mode: bool = True

    omniroute_api_key: str | None = Field(default=None, repr=False)
    omniroute_base_url: str = "https://omnirouters.com/v1"
    omniroute_default_model: str = "opencode-zen/deepseek-v4-flash"
    omniroute_image_model: str = "chatgpt-web/gpt-5.5"
    omniroute_video_model: str = "veo-3.1-fast-generate-preview"
    omniroute_speech_model: str = ""
    omniroute_image_timeout_seconds: int = 360
    omniroute_video_submit_timeout_seconds: int = 180
    omniroute_video_poll_interval_seconds: int = 8
    omniroute_video_poll_timeout_seconds: int = 900
    omniroute_video_download_timeout_seconds: int = 300
    ai_provider: str = "ollama_cloud"
    text_provider: str | None = "ollama_cloud"
    text_provider_fallbacks: str = ""
    ollama_cloud_api_key: str | None = Field(default=None, repr=False)
    ollama_cloud_base_url: str = "https://ollama.com/api"
    ollama_cloud_default_model: str = OLLAMA_CLOUD_TEXT_MODELS[0]
    google_ai_api_key: str | None = Field(default=None, repr=False)
    google_ai_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    google_ai_image_model: str = GOOGLE_AI_IMAGE_MODELS[0]
    google_ai_image_size: str = "1K"
    google_ai_video_model: str = GOOGLE_AI_VIDEO_MODELS[0]
    google_ai_video_fast_model: str = GOOGLE_AI_VIDEO_MODELS[0]
    google_ai_video_default_duration_seconds: int = 8
    google_ai_video_poll_interval_seconds: int = 10
    google_ai_video_poll_timeout_seconds: int = 900
    image_provider: str | None = "google_ai"
    video_provider: str | None = "google_ai"
    storyboard_image_concurrency: int = 3
    video_generation_concurrency: int = Field(default=2, ge=1, le=4)
    speech_provider: str = "elevenlabs"
    speech_base_url: str = "https://api.openai.com/v1"
    speech_api_key: str | None = Field(default=None, repr=False)
    speech_model: str = ""
    speech_voice: str = "alloy"
    speech_timeout_seconds: int = 120
    elevenlabs_api_key: str | None = Field(default=None, repr=False)
    elevenlabs_base_url: str = "https://api.elevenlabs.io/v1"
    elevenlabs_voice_id: str = ""
    elevenlabs_speech_model: str = "eleven_multilingual_v2"
    elevenlabs_output_format: str = "mp3_44100_128"
    dubbing_provider: str = "elevenlabs"
    dubbing_source_lang: str = "pt"
    dubbing_target_lang: str = "en"
    dubbing_poll_interval_seconds: int = 10
    dubbing_poll_timeout_seconds: int = 900
    user_display_name: str = "Jonata"
    user_email: str = ""
    user_avatar_path: str = ""
    user_theme: str = "dark"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def reject_insecure_non_local_defaults(self) -> "Settings":
        self.omniroute_api_key = normalize_omniroute_api_key(self.omniroute_api_key)
        self.ollama_cloud_api_key = normalize_api_key(
            self.ollama_cloud_api_key, "ollama_cloud"
        )
        self.ollama_cloud_default_model = normalize_ollama_cloud_text_model(
            self.ollama_cloud_default_model
        )
        self.google_ai_api_key = normalize_api_key(self.google_ai_api_key, "google_ai")
        self.google_ai_image_model = normalize_google_ai_image_model(self.google_ai_image_model)
        self.google_ai_video_model = normalize_google_ai_video_model(self.google_ai_video_model)
        self.google_ai_video_fast_model = normalize_google_ai_video_model(
            self.google_ai_video_fast_model
        )
        self.elevenlabs_api_key = normalize_api_key(self.elevenlabs_api_key, "elevenlabs")
        self.ai_provider = normalize_provider_name(self.ai_provider, "AI_PROVIDER")
        self.text_provider = self._optional_provider(self.text_provider, "TEXT_PROVIDER")
        self.image_provider = self._optional_provider(
            self.image_provider,
            "IMAGE_PROVIDER",
            legacy_default="google_ai",
        )
        self.video_provider = self._optional_provider(
            self.video_provider,
            "VIDEO_PROVIDER",
            legacy_default="google_ai",
        )
        if self.app_env.lower() not in {"local", "development", "test"}:
            if self.app_secret_key == "change-me-in-development":
                raise ValueError("APP_SECRET_KEY must be changed outside local environments")
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false outside local environments")
        return self

    @staticmethod
    def _optional_provider(
        value: str | None,
        field_name: str,
        *,
        legacy_default: str = "ollama_cloud",
    ) -> str | None:
        if not str(value or "").strip():
            return None
        text = str(value or "").strip().casefold()
        if text in {"omniroute", "opencode"}:
            return legacy_default
        return normalize_provider_name(value, field_name)


def normalize_ollama_cloud_text_model(value: object) -> str:
    model = str(value or "").strip()
    if model in OLLAMA_CLOUD_TEXT_MODELS:
        return model
    return OLLAMA_CLOUD_TEXT_MODELS[0]


def normalize_google_ai_image_model(value: object) -> str:
    model = str(value or "").strip()
    if model in GOOGLE_AI_IMAGE_MODELS:
        return model
    return GOOGLE_AI_IMAGE_MODELS[0]


def normalize_google_ai_video_model(value: object) -> str:
    model = str(value or "").strip()
    if model in GOOGLE_AI_VIDEO_MODELS:
        return model
    return GOOGLE_AI_VIDEO_MODELS[0]


@lru_cache
def get_settings() -> Settings:
    from app.config.runtime_preferences import load_runtime_preferences

    return Settings(**cast(dict[str, Any], load_runtime_preferences()))
