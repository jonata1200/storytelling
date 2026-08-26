from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field, model_validator

from app.config.settings import get_settings


class VideoImageInput(BaseModel):
    """Imagem de referencia ou de ancora (frame) enviada ao provedor de video."""

    url: str
    frame_type: str | None = None


class VideoIngredientInput(BaseModel):
    """Referência já sincronizada no provider, versionada pela bíblia visual."""

    id: str
    type: str
    reference_id: str


class VideoGenerationRequest(BaseModel):
    model: str
    prompt: str
    duration: int = 8
    aspect_ratio: str = "9:16"
    resolution: str = "720p"
    seed: int | None = None
    frame_images: list[VideoImageInput] = Field(default_factory=list)
    input_references: list[VideoImageInput] = Field(default_factory=list)
    ingredients: list[VideoIngredientInput] = Field(default_factory=list)
    output_dir: Path
    # Chave de persistência no provedor: todos os vídeos de um projeto do
    # storytelling são gerados no MESMO projeto Vibes (espelha a conversa
    # única da Bíblia Visual no Meta AI).
    project_key: str | None = None

    @model_validator(mode="after")
    def _validate_output_dir_within_storage(self) -> "VideoGenerationRequest":
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


class VideoJob(BaseModel):
    id: str
    polling_url: str = ""
    project_url: str = ""
    status: str = "pending"
    error: str | None = None
    unsigned_urls: list[str] = Field(default_factory=list)
    provider: str = ""
    model: str = ""
    prompt: str = ""


class VideoJobUpdate(BaseModel):
    status: str
    unsigned_urls: list[str] = Field(default_factory=list)
    project_url: str = ""
    error: str | None = None
    usage_cost: str | None = None


class VideoGenerationResult(BaseModel):
    file_path: Path
    storage_uri: str
    sha256: str
    content_type: str
    provider: str
    model: str
    prompt: str
    estimated_cost: str = "0.000000"
    job_id: str = ""


class VideoProvider(Protocol):
    provider_name: str

    async def submit(self, request: VideoGenerationRequest) -> VideoJob:
        """Submete um job assíncrono de geração de vídeo."""
        ...

    async def poll(self, job: VideoJob) -> VideoJobUpdate:
        """Consulta o status do job até um estado terminal ou pendente."""
        ...

    async def download(self, job: VideoJob, output_dir: Path) -> VideoGenerationResult:
        """Baixa o vídeo concluído e salva dentro de output_dir."""
        ...
