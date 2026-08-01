import sys
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.provider_policy import (
    effective_provider_for_channel,
    provider_model,
)
from app.config.settings import get_settings
from app.production.service import get_or_create_production_settings, resolve_image_model
from app.providers.image.google_ai import GoogleAIImageProvider
from app.providers.image.types import ImageGenerationRequest, ImageProvider, ImageResult
from app.providers.image.veo_ai_free import VeoAiFreeImageProvider


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
    model = resolve_image_model(
        production_settings.image_model,
        provider_model(app_settings, provider, "image"),
    )
    if provider == "veo_ai_free":
        return VeoAiFreeImageProvider(), model, "veo_ai_free_images"
    if provider == "google_ai":
        return GoogleAIImageProvider(), model, "google_ai_images"
    raise ValueError("Provider de imagem não suportado. Use Google AI ou Veo AI Free.")


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
        if getattr(provider, "provider_name", "") != "veo_ai_free" or not (
            _transient_image_provider_error(exc)
        ):
            raise
        provider_label = "Veo AI Free Images"
        raise RuntimeError(
            f"{provider_label} falhou ao gerar a imagem real. Nenhuma imagem mock foi criada "
            f"automaticamente. Detalhes: {exc}"
        ) from exc
