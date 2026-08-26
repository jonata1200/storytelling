from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field, model_validator

from app.config.settings import get_settings


class ImageReference(BaseModel):
    uri: str
    role: str | None = None
    weight: float | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model: str
    aspect_ratio: str = "9:16"
    references: list[ImageReference] = Field(default_factory=list)
    output_dir: Path
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_output_dir(self) -> "ImageGenerationRequest":
        storage_root = get_settings().local_storage_path.resolve()
        resolved_output = self.output_dir.resolve(strict=False)
        try:
            resolved_output.relative_to(storage_root)
        except ValueError as exc:
            raise ValueError(
                f"output_dir deve estar dentro do storage root ({storage_root}). "
                f"Recebido: {self.output_dir}"
            ) from exc
        return self


class ImageGenerationJob(BaseModel):
    id: str
    status: str = "pending"
    polling_url: str = ""
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageGenerationResult(BaseModel):
    file_path: Path
    storage_uri: str
    sha256: str
    content_type: str
    provider: str
    model: str
    prompt: str
    external_job_id: str = ""
    estimated_cost: str = "0.000000"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageProvider(Protocol):
    provider_name: str

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        ...
