from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class SpeechRequest(BaseModel):
    text: str
    output_dir: Path
    model: str = ""


class SpeechResult(BaseModel):
    file_path: Path
    storage_uri: str
    sha256: str
    content_type: str = ""
    provider: str = ""
    model: str = ""
    duration_seconds: int = 0
    alignment: dict = {}
    estimated_cost: str = "0.000000"


class SpeechProvider(Protocol):
    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        ...
