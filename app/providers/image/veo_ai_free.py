import hashlib
from uuid import uuid4

from app.config.provider_policy import validate_model_name
from app.config.settings import get_settings
from app.providers.image.types import ImageEditRequest, ImageGenerationRequest, ImageResult
from app.providers.media_utils import extension_from_media_type
from app.providers.veo_free.browser import VeoFreeBrowserClient
from app.providers.veo_free.session import validate_session


class VeoAiFreeImageProvider:
    provider_name = "veo_ai_free"

    def __init__(self, client: VeoFreeBrowserClient | None = None) -> None:
        self.client = client or VeoFreeBrowserClient()

    async def generate(self, request: ImageGenerationRequest) -> ImageResult:
        settings = get_settings()
        if not settings.veo_ai_free_enabled:
            raise RuntimeError("Veo AI Free experimental esta desabilitado.")
        validation = validate_session(settings.veo_ai_free_session_path)
        if validation.status != "connected":
            raise RuntimeError(f"Reconecte o Veo AI Free manualmente: {validation.message}")
        model = validate_model_name(request.model, provider=self.provider_name)
        prompt = request.prompt
        if request.negative_prompt:
            prompt = f"{prompt}\nEvite: {request.negative_prompt}"
        media = await self.client.generate_image(
            {
                "prompt": prompt,
                "aspect_ratio": request.aspect_ratio,
                "resolution": request.resolution,
                "references": request.references,
                "model": model,
            }
        )
        request.output_dir.mkdir(parents=True, exist_ok=True)
        extension = extension_from_media_type(media.content_type)
        safe_view = request.view_type.replace("/", "_").replace("\\", "_")
        filename = f"{request.target_id}_{safe_view}_{uuid4().hex[:8]}{extension}"
        file_path = request.output_dir / filename
        file_path.write_bytes(media.media_bytes)
        sha256 = hashlib.sha256(media.media_bytes).hexdigest()
        return ImageResult(
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256=sha256,
            content_type=media.content_type,
            provider=self.provider_name,
            model=model,
            prompt=prompt,
            estimated_cost="0.000000",
        )

    async def edit(self, request: ImageEditRequest) -> ImageResult:
        return await self.generate(
            ImageGenerationRequest(
                prompt=request.prompt,
                target_id="edit",
                view_type="variant",
                output_dir=request.output_dir,
                references=[request.source_uri],
                model=request.model,
            )
        )
