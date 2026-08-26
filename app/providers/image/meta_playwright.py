import asyncio
import hashlib
from pathlib import Path

from app.config.settings import get_settings
from app.providers.browser_bridge import run_browser_bridge
from app.providers.image.types import ImageGenerationRequest, ImageGenerationResult


class PlaywrightMetaImageBrowserBackend:
    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        settings = get_settings()
        response = await run_browser_bridge(
            "generate-image",
            {
                "profilePath": str(settings.meta_browser_profile_path),
                "prompt": request.prompt,
                "aspectRatio": request.aspect_ratio,
                "outputDir": str(request.output_dir),
                "references": [item.uri for item in request.references],
                "conversationKey": str(request.metadata.get("project_id") or "default"),
                "timeoutSeconds": settings.meta_image_timeout_seconds,
                # Espera extra pela conclusão da geração anterior ANTES de
                # enviar um novo prompt (gate de conclusão no bridge). Evita
                # que um retry dispare um segundo prompt com a Meta AI ainda
                # gerando a tentativa anterior na mesma conversa.
                "settledWaitSeconds": settings.meta_image_settled_wait_seconds,
            },
            timeout_seconds=settings.meta_image_timeout_seconds
            + settings.meta_image_settled_wait_seconds
            + 60,
        )
        path = await asyncio.to_thread(
            lambda: Path(str(response["filePath"])).resolve(strict=True)
        )
        content = await asyncio.to_thread(path.read_bytes)
        return ImageGenerationResult(
            file_path=path,
            storage_uri=path.as_posix(),
            sha256=hashlib.sha256(content).hexdigest(),
            content_type=str(response["contentType"]),
            provider="meta",
            model=request.model,
            prompt=request.prompt,
            external_job_id=str(response.get("jobId") or ""),
            metadata={
                "source": "meta.ai",
                "automation": "playwright",
                "conversation_url": str(response.get("conversationUrl") or ""),
            },
        )
