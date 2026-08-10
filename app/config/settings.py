from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.provider_policy import normalize_api_key, normalize_provider_name

DEFAULT_APP_SECRET_KEY = "change-me-in-development"

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
    "veo-3.1-lite-generate-preview",
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
    app_secret_key: str = Field(default=DEFAULT_APP_SECRET_KEY, repr=False)

    database_url: str = "postgresql+asyncpg://storytelling:storytelling@localhost:5432/storytelling"
    redis_url: str = "redis://localhost:6379/0"

    storage_backend: str = "local"
    local_storage_path: Path = Path("./storage")
    max_upload_bytes: int = 25 * 1024 * 1024
    max_generated_asset_bytes: int = 750 * 1024 * 1024
    allow_user_registration: bool = True
    single_user_mode: bool = True

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
        )
        self.video_provider = self._optional_provider(
            self.video_provider,
            "VIDEO_PROVIDER",
        )
        if self.app_env.lower() not in {"local", "development", "test"}:
            if self.app_secret_key == DEFAULT_APP_SECRET_KEY:
                raise ValueError("APP_SECRET_KEY must be changed outside local environments")
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false outside local environments")
        return self

    @staticmethod
    def _optional_provider(
        value: str | None,
        field_name: str,
    ) -> str | None:
        if not str(value or "").strip():
            return None
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


def insecure_default_secret_key_warning() -> str | None:
    settings = get_settings()
    if settings.app_secret_key != DEFAULT_APP_SECRET_KEY:
        return None
    return (
        "APP_SECRET_KEY ainda usa o valor padrão de desenvolvimento. Qualquer pessoa com "
        "acesso ao repositório pode forjar tokens de sessão e CSRF. Defina um segredo "
        "próprio antes de expor a aplicação."
    )
