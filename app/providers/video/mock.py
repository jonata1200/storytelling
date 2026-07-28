import hashlib
import json
from pathlib import Path
from uuid import uuid4

from app.core.enums import GenerationJobStatus
from app.providers.video.types import ProviderCapabilities, VideoRequest, VideoResult
from app.video_generation.durations import (
    VIDEO_CLIP_MAX_SECONDS,
    VIDEO_CLIP_MIN_SECONDS,
    validate_video_clip_duration,
)


class MockVideoProvider:
    provider_name = "mock"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text_to_video=True,
            image_to_video=True,
            reference_images=True,
            first_frame=True,
            supported_durations=list(range(VIDEO_CLIP_MIN_SECONDS, VIDEO_CLIP_MAX_SECONDS + 1)),
            supported_aspect_ratios=["9:16"],
            max_reference_images=4,
        )

    async def generate_from_text(self, request: VideoRequest) -> VideoResult:
        return await self._generate(request, mode="text_to_video")

    async def generate_from_image(self, request: VideoRequest) -> VideoResult:
        return await self._generate(request, mode="image_to_video")

    async def get_status(self, external_job_id: str) -> GenerationJobStatus:
        return GenerationJobStatus.SUCCEEDED

    async def cancel(self, external_job_id: str) -> None:
        return None

    async def _generate(self, request: VideoRequest, mode: str) -> VideoResult:
        duration_seconds = validate_video_clip_duration(request.duration_seconds)
        request.output_dir.mkdir(parents=True, exist_ok=True)
        external_job_id = f"mock-video-{uuid4().hex}"
        file_path = request.output_dir / f"{external_job_id}.mockvideo.json"
        payload = {
            "external_job_id": external_job_id,
            "mode": mode,
            "prompt": request.prompt,
            "duration_seconds": duration_seconds,
            "aspect_ratio": request.aspect_ratio,
            "source_image_uri": request.source_image_uri,
            "reference_uris": request.reference_uris,
            "model": request.model,
            "seed": request.seed,
        }
        serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
        file_path.write_text(serialized, encoding="utf-8")
        sha256 = hashlib.sha256(serialized.encode()).hexdigest()
        return VideoResult(
            external_job_id=external_job_id,
            status=GenerationJobStatus.SUCCEEDED,
            file_path=file_path,
            storage_uri=self._storage_uri(file_path),
            sha256=sha256,
            provider=self.provider_name,
            model=request.model,
            metadata=payload,
        )

    def _storage_uri(self, file_path: Path) -> str:
        return file_path.as_posix()
