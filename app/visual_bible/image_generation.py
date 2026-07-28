import sys
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.model_policy import ensure_openrouter_api_key
from app.config.provider_policy import (
    effective_provider_for_channel,
    provider_model,
    unavailable_provider_error,
)
from app.config.settings import get_settings
from app.production.service import get_or_create_production_settings, resolve_image_model
from app.providers.image.openrouter import OpenRouterImageProvider
from app.providers.image.types import ImageGenerationRequest, ImageProvider, ImageResult


def _service_attr(name: str, fallback: object) -> Any:
    service = sys.modules.get("app.visual_bible.service")
    return getattr(service, name, fallback) if service is not None else fallback


async def _image_provider_for_project(
    session: AsyncSession, project_id: UUID
) -> tuple[ImageProvider, str, str]:
    settings_factory = _service_attr("get_settings", get_settings)
    production_settings_factory = _service_attr(
        "get_or_create_production_settings",
        get_or_create_production_settings,
    )
    app_settings = settings_factory()
    production_settings = await production_settings_factory(session, project_id)
    provider = effective_provider_for_channel(app_settings, "image")
    if provider == "omniroute":
        raise unavailable_provider_error("omniroute", "fase 4")
    model = resolve_image_model(
        production_settings.image_model,
        provider_model(app_settings, provider, "image"),
    )
    ensure_openrouter_api_key(app_settings.openrouter_api_key)
    return OpenRouterImageProvider(), model, "openrouter_images"


def _transient_image_provider_error(exc: Exception) -> bool:
    message = str(exc).lower()
    transient_terms = (
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "sourceful",
        "internal error",
        "temporarily unavailable",
        "timeout",
        "timed out",
        "network",
        "connection",
    )
    return any(term in message for term in transient_terms)


async def _generate_image_with_provider_fallback(
    provider: ImageProvider,
    request: ImageGenerationRequest,
) -> tuple[ImageResult, dict]:
    try:
        return await provider.generate(request), {}
    except RuntimeError as exc:
        if getattr(
            provider, "provider_name", ""
        ) != "openrouter" or not _transient_image_provider_error(exc):
            raise
        raise RuntimeError(
            "OpenRouter Images falhou ao gerar a imagem real. Nenhuma imagem mock foi criada "
            f"automaticamente. Detalhes: {exc}"
        ) from exc
