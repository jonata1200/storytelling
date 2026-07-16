import hashlib
import wave
from pathlib import Path
from uuid import uuid4

from app.providers.speech.types import SpeechRequest, SpeechResult
from app.storyboards.timeline import build_word_alignment


class MockSpeechProvider:
    provider_name = "mock"

    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        duration_seconds = self._estimate_duration(request.text, request.speed)
        file_path = request.output_dir / f"speech_{uuid4().hex[:8]}.wav"
        self._write_silence(file_path, duration_seconds)
        file_bytes = file_path.read_bytes()
        return SpeechResult(
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256=hashlib.sha256(file_bytes).hexdigest(),
            provider=self.provider_name,
            model=request.model,
            duration_seconds=duration_seconds,
            alignment=build_word_alignment(request.text, duration_seconds),
        )

    def _estimate_duration(self, text: str, speed: float) -> int:
        words = max(1, len(text.split()))
        words_per_second = max(1.0, 2.6 * speed)
        return max(1, int(round(words / words_per_second)))

    def _write_silence(self, file_path: Path, duration_seconds: int) -> None:
        sample_rate = 16_000
        frame_count = sample_rate * duration_seconds
        with wave.open(str(file_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"\x00\x00" * frame_count)
