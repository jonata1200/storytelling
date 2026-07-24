from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from app.core.enums import GenerationJobStatus


class ProviderCapabilities(BaseModel):
    text_to_video: bool = False
    image_to_video: bool = False
    reference_images: bool = False
    character_reference: bool = False
    first_frame: bool = False
    last_frame: bool = False
    native_audio: bool = False
    supported_durations: list[int] = Field(default_factory=list)
    supported_aspect_ratios: list[str] = Field(default_factory=list)
    max_reference_images: int = 0


class VideoRequest(BaseModel):
    prompt: str
    duration_seconds: int
    aspect_ratio: str = "9:16"
    resolution: str | None = None
    size: str | None = None
    source_image_uri: str | None = None
    reference_uris: list[str] = Field(default_factory=list)
    output_dir: Path
    model: str = "bytedance/seedance-2.0-fast"
    seed: int | None = None


class VideoResult(BaseModel):
    external_job_id: str
    status: GenerationJobStatus
    file_path: Path | None = None
    storage_uri: str | None = None
    sha256: str | None = None
    content_type: str = "video/mp4"
    provider: str
    model: str
    estimated_cost: str = "0.000000"
    metadata: dict = Field(default_factory=dict)


class VideoProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities:
        ...

    async def generate_from_text(self, request: VideoRequest) -> VideoResult:
        ...

    async def generate_from_image(self, request: VideoRequest) -> VideoResult:
        ...

    async def get_status(self, external_job_id: str) -> GenerationJobStatus:
        ...

    async def cancel(self, external_job_id: str) -> None:
        ...
