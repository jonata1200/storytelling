import asyncio
from pathlib import Path

from app.config.provider_policy import provider_integration_mode, validate_model_name
from app.config.settings import get_settings
from app.providers.image.meta_browser import (
    MetaImageBrowserBackend,
    load_meta_image_browser_backend,
)
from app.providers.image.types import ImageGenerationRequest, ImageGenerationResult


class MetaImageProvider:
    provider_name = "meta"
    display_name = "Meta Image"

    def __init__(self, browser_backend: MetaImageBrowserBackend | None = None) -> None:
        self._browser = browser_backend or load_meta_image_browser_backend()

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        settings = get_settings()
        if provider_integration_mode(settings, self.provider_name, "image") != "browser":
            raise RuntimeError("Meta Image aceita somente META_IMAGE_INTEGRATION_MODE=browser")
        if not settings.meta_browser_automation_enabled:
            raise RuntimeError(
                "Habilite META_BROWSER_AUTOMATION_ENABLED somente após instalar e autorizar "
                "o backend de browser do Meta Image."
            )
        normalized = request.model_copy(
            update={"model": validate_model_name(request.model, provider=self.provider_name)}
        )
        result = await self._browser.generate(normalized)
        await asyncio.to_thread(_validate_result, result, normalized.output_dir)
        if result.provider != self.provider_name:
            result = result.model_copy(update={"provider": self.provider_name})
        return result


def _validate_result(result: ImageGenerationResult, output_dir: Path) -> None:
    resolved_output = output_dir.resolve(strict=False)
    resolved_file = result.file_path.resolve(strict=True)
    try:
        resolved_file.relative_to(resolved_output)
    except ValueError as exc:
        raise ValueError("Meta Image retornou arquivo fora do diretório de saída") from exc
    content = resolved_file.read_bytes()
    media_type = result.content_type.split(";", 1)[0].strip().lower()
    valid = (
        media_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n")
    ) or (media_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff")) or (
        media_type == "image/webp"
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP"
    )
    if not valid:
        raise ValueError("Meta Image retornou arquivo vazio, parcial ou inválido")
