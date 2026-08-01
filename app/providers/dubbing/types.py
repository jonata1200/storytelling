from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field


class DubbingSubmitRequest(BaseModel):
    file_path: Path
    name: str
    source_language: str | None = None
    target_language: str


class DubbingSubmitResult(BaseModel):
    external_job_id: str
    expected_duration_seconds: float | None = None
    metadata: dict = Field(default_factory=dict)


class DubbingStatusResult(BaseModel):
    external_job_id: str
    status: str
    source_language: str | None = None
    target_languages: list[str] = Field(default_factory=list)
    error: str | None = None
    metadata: dict = Field(default_factory=dict)


class DubbingDownloadResult(BaseModel):
    content: bytes
    content_type: str
    metadata: dict = Field(default_factory=dict)


class DubbingProvider(Protocol):
    provider_name: str

    def submit(self, request: DubbingSubmitRequest) -> DubbingSubmitResult:
        ...

    def status(self, external_job_id: str) -> DubbingStatusResult:
        ...

    def download(self, external_job_id: str, language_code: str) -> DubbingDownloadResult:
        ...
