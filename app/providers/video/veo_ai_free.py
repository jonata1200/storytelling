import hashlib

from app.config.provider_policy import validate_model_name
from app.config.settings import get_settings
from app.core.enums import GenerationJobStatus
from app.providers.veo_free.browser import VeoFreeBrowserClient
from app.providers.veo_free.session import validate_session
from app.providers.video.types import ProviderCapabilities, VideoRequest, VideoResult
from app.video_generation.durations import (
    VIDEO_CLIP_MAX_SECONDS,
    VIDEO_CLIP_MIN_SECONDS,
    validate_video_clip_duration,
)


class VeoAiFreeVideoProvider:
    provider_name = "veo_ai_free"

    def __init__(self, client: VeoFreeBrowserClient | None = None) -> None:
        self.client = client or VeoFreeBrowserClient()

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text_to_video=True,
            image_to_video=True,
            reference_images=True,
            first_frame=True,
            supported_durations=list(range(VIDEO_CLIP_MIN_SECONDS, VIDEO_CLIP_MAX_SECONDS + 1)),
            supported_aspect_ratios=["9:16", "16:9", "1:1"],
            max_reference_images=4,
        )

    async def generate_from_text(self, request: VideoRequest) -> VideoResult:
        return await self._generate(request, mode="text_to_video")

    async def generate_from_image(self, request: VideoRequest) -> VideoResult:
        return await self._generate(request, mode="image_to_video")

    async def get_status(self, external_job_id: str) -> GenerationJobStatus:
        _ = external_job_id
        return GenerationJobStatus.SUCCEEDED

    async def cancel(self, external_job_id: str) -> None:
        _ = external_job_id

    async def _generate(self, request: VideoRequest, mode: str) -> VideoResult:
        settings = get_settings()
        if not settings.veo_ai_free_enabled:
            raise RuntimeError("Veo AI Free experimental esta desabilitado.")
        validation = validate_session(settings.veo_ai_free_session_path)
        if validation.status != "connected":
            raise RuntimeError(f"Reconecte o Veo AI Free manualmente: {validation.message}")
        duration_seconds = validate_video_clip_duration(request.duration_seconds)
        model = validate_model_name(request.model, provider=self.provider_name)
        media = await self.client.generate_video(
            {
                "mode": mode,
                "prompt": request.prompt,
                "duration_seconds": duration_seconds,
                "aspect_ratio": request.aspect_ratio,
                "resolution": request.resolution,
                "size": request.size,
                "source_image_uri": request.source_image_uri,
                "reference_uris": request.reference_uris,
                "model": model,
                "seed": request.seed,
            }
        )
        request.output_dir.mkdir(parents=True, exist_ok=True)
        file_path = request.output_dir / f"{media.external_job_id}.mp4"
        file_path.write_bytes(media.media_bytes)
        sha256 = hashlib.sha256(media.media_bytes).hexdigest()
        return VideoResult(
            external_job_id=media.external_job_id,
            status=GenerationJobStatus.SUCCEEDED,
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256=sha256,
            provider=self.provider_name,
            model=model,
            metadata=media.metadata | {"experimental": True, "mode": mode},
        )
