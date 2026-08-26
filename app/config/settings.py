import os
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.provider_policy import normalize_api_key

DEFAULT_APP_SECRET_KEY = "change-me-in-development"

DEFAULT_OLLAMA_TEXT_MODEL = "gemma4:31b-cloud"
DEFAULT_OLLAMA_VISION_MODEL = "gemma3"

# Modelos de texto disponíveis no Ollama Cloud, em ordem alfabética.
OLLAMA_CLOUD_TEXT_MODELS = (
    "deepseek-v4-flash:0731-cloud",
    "deepseek-v4-pro:0813-cloud",
    "gemma4:31b-cloud",
    "glm-5.3-flash:cloud",
    "minimax-m2.7:cloud",
    "minimax-m3:cloud",
    "mistral-large-3:675b-cloud",
    "nemotron-3-super:cloud",
    "nemotron-3-ultra:cloud",
)


class Settings(BaseSettings):
    app_name: str = "Storytelling"
    app_env: str = "local"
    app_debug: bool = True
    app_secret_key: str = Field(default=DEFAULT_APP_SECRET_KEY, repr=False)
    app_api_token: str = Field(default="", repr=False)

    database_url: str = Field(default="", repr=False)
    redis_url: str = Field(default="redis://localhost:6379/0", repr=False)
    worker_queue_name: str = "storytelling:media-jobs"
    worker_consumer_group: str = "storytelling-workers"
    worker_heartbeat_seconds: int = Field(default=10, ge=2, le=60)
    worker_reclaim_seconds: int = Field(default=120, ge=30, le=3600)
    worker_vibes_concurrency: int = Field(default=1, ge=1, le=2)
    worker_meta_image_concurrency: int = Field(default=2, ge=1, le=4)
    shot_auto_regeneration_enabled: bool = True
    shot_auto_regeneration_max_attempts: int = Field(default=2, ge=0, le=5)
    qa_auto_reject_objective_failures: bool = True
    qa_ollama_multimodal_enabled: bool = True
    qa_ollama_timeout_seconds: float = Field(default=120, ge=15, le=600)
    worker_rate_limit_seconds: float = Field(default=0.25, ge=0, le=30)

    storage_backend: str = "local"
    local_storage_path: Path = Path("./storage")
    max_generated_asset_bytes: int = 750 * 1024 * 1024

    text_provider: str | None = "ollama_cloud"
    image_provider: str | None = "meta"
    ollama_cloud_integration_mode: str = "api"
    ollama_cloud_api_key: str | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices(
            "ollama_cloud_api_key", "OLLAMA_API_KEY", "OLLAMA_CLOUD_API_KEY"
        ),
    )
    ollama_cloud_base_url: str = "https://ollama.com/api"
    ollama_cloud_default_model: str = DEFAULT_OLLAMA_TEXT_MODEL
    ollama_cloud_vision_model: str = DEFAULT_OLLAMA_VISION_MODEL
    meta_image_integration_mode: str = "browser"
    meta_image_model: str = "muse-image"
    meta_image_timeout_seconds: float = Field(default=180, ge=15, le=600)
    # Espera extra (no bridge) pela CONCLUSÃO da geração anterior antes de
    # enviar um novo prompt na mesma conversa. Zerar desativa a espera — o
    # comportamento volta a ser o antigo (envio imediato).
    meta_image_settled_wait_seconds: float = Field(default=240, ge=0, le=900)
    meta_browser_automation_enabled: bool = False
    meta_browser_profile_path: Path = Path("./runtime/browser_profiles/meta")
    ffmpeg_path: str = ""
    video_generation_concurrency: int = Field(default=2, ge=1, le=4)
    video_provider: str | None = "vibes"
    vibes_integration_mode: str = "browser"
    vibes_api_key: str | None = Field(default=None, repr=False)
    vibes_base_url: str = ""
    vibes_video_model: str = "vibes"
    vibes_browser_automation_enabled: bool = False
    vibes_browser_profile_path: Path = Path("./runtime/browser_profiles/vibes")
    user_theme: str = "dark"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def reject_insecure_non_local_defaults(self) -> "Settings":
        self.ollama_cloud_api_key = normalize_api_key(self.ollama_cloud_api_key)
        self.vibes_api_key = normalize_api_key(self.vibes_api_key)
        # Cutover: providers fixos por decisão de produto. Valores de
        # TEXT_PROVIDER / IMAGE_PROVIDER / VIDEO_PROVIDER no ambiente são
        # intencionalmente ignorados até que novos adapters sejam suportados.
        self.text_provider = "ollama_cloud"
        self.image_provider = "meta"
        self.video_provider = "vibes"
        self.ollama_cloud_integration_mode = self._integration_mode(
            self.ollama_cloud_integration_mode, "OLLAMA_CLOUD_INTEGRATION_MODE"
        )
        self.meta_image_integration_mode = self._integration_mode(
            self.meta_image_integration_mode, "META_IMAGE_INTEGRATION_MODE"
        )
        self.vibes_integration_mode = self._integration_mode(
            self.vibes_integration_mode, "VIBES_INTEGRATION_MODE"
        )
        self.meta_browser_profile_path = self._browser_profile_path(
            self.meta_browser_profile_path, "META_BROWSER_PROFILE_PATH"
        )
        self.vibes_browser_profile_path = self._browser_profile_path(
            self.vibes_browser_profile_path, "VIBES_BROWSER_PROFILE_PATH"
        )
        if self.app_env.lower() not in {"local", "development", "test"}:
            if self.app_secret_key == DEFAULT_APP_SECRET_KEY:
                raise ValueError("APP_SECRET_KEY must be changed outside local environments")
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false outside local environments")
            if not self.database_url.strip():
                raise ValueError("DATABASE_URL must be set outside local environments")
        # SEC-04: URLs de LLM não podem usar esquemas arbitrários (S310) — o
        # endpoint faz urlopen com essa URL; https é o único esquema aceito.
        if self.ollama_cloud_base_url.strip() and not (
            self.ollama_cloud_base_url.strip().startswith(("https://", "http://localhost"))
        ):
            raise ValueError(
                "OLLAMA_CLOUD_BASE_URL inválida: use uma URL https:// "
                f"(recebido: {self.ollama_cloud_base_url!r})"
            )
        # SEC-03: o secret local é resolvido após o storage, no fim do validador.
        if not self.database_url.strip():
            self.database_url = (
                "postgresql+asyncpg://storytelling:storytelling@localhost:5433/storytelling"
            )
        # Resolve o storage como caminho absoluto para que iniciar a aplicação a
        # partir de outro diretório não crie um diretório storage inesperado.
        resolved_storage = self.local_storage_path
        if not resolved_storage.is_absolute():
            resolved_storage = (Path.cwd() / resolved_storage).resolve(strict=False)
        else:
            resolved_storage = resolved_storage.resolve(strict=False)
        self.local_storage_path = resolved_storage
        if self.app_env.lower() in {"local", "development", "test"} and (
            self.app_secret_key == DEFAULT_APP_SECRET_KEY
        ):
            # SEC-03: só depois do storage resolvido — o secret é persistido em
            # <repo>/.runtime/app_secret_key.
            from app.config.local_secret import load_or_create_local_secret_key

            self.app_secret_key = load_or_create_local_secret_key(self.local_storage_path)
        return self

    @staticmethod
    def _integration_mode(value: object, field_name: str) -> str:
        mode = str(value or "").strip().casefold()
        if mode not in {"api", "browser"}:
            raise ValueError(f"{field_name} inválido: {mode or '(vazio)'}. Use: api, browser")
        return mode

    @staticmethod
    def _browser_profile_path(value: Path, field_name: str) -> Path:
        # realpath resolve symlinks/junctions inclusive no Windows, onde
        # Path.resolve(strict=False) pode não normalizar junctions corretamente.
        root = Path(os.path.realpath(Path.cwd() / "runtime" / "browser_profiles"))
        resolved = Path(os.path.realpath(value))
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"{field_name} deve ficar dentro de {root}. Recebido: {value}"
            ) from exc
        return resolved

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
