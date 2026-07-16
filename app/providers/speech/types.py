from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class SpeechRequest(BaseModel):
    text: str
    voice_profile_id: str
    output_dir: Path
    speed: float = 1.0
    emotion: str = "warm"
    model: str = "mock-speech"


class SpeechResult(BaseModel):
    file_path: Path
    storage_uri: str
    sha256: str
    content_type: str = "audio/wav"
    provider: str
    model: str
    duration_seconds: int
    alignment: dict
    estimated_cost: str = "0.000000"


class SpeechProvider(Protocol):
    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        ...
