from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field


class ImageGenerationRequest(BaseModel):
    prompt: str
    target_id: str
    view_type: str
    output_dir: Path
    aspect_ratio: str = "9:16"
    resolution: str | None = None
    negative_prompt: str | None = None
    references: list[str] = Field(default_factory=list)
    model: str = "chatgpt-web/gpt-5.5"


class ImageEditRequest(BaseModel):
    prompt: str
    source_uri: str
    output_dir: Path
    model: str = "chatgpt-web/gpt-5.5"


class ImageResult(BaseModel):
    file_path: Path
    storage_uri: str
    sha256: str
    content_type: str
    provider: str
    model: str
    prompt: str
    estimated_cost: str = "0.000000"


class ImageProvider(Protocol):
    async def generate(self, request: ImageGenerationRequest) -> ImageResult:
        ...

    async def edit(self, request: ImageEditRequest) -> ImageResult:
        ...
