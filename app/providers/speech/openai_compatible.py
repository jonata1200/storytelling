import asyncio
import hashlib
import json
import urllib.error
import urllib.request
from typing import Any
from uuid import uuid4

from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.speech.types import SpeechRequest, SpeechResult
from app.storyboards.timeline import build_word_alignment


class OpenAICompatibleSpeechProvider:
    provider_name = "openai_compatible"

    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        return await asyncio.to_thread(self._synthesize, request)

    def _synthesize(self, request: SpeechRequest) -> SpeechResult:
        settings = get_settings()
        api_key = settings.speech_api_key
        if not api_key:
            raise RuntimeError("SPEECH_API_KEY nao configurada para provider de voz real")
        model = request.model or settings.speech_model
        if not model:
            raise RuntimeError("SPEECH_MODEL nao configurado para provider de voz real")

        body = self._speech_request_body(request, model, settings.speech_voice)
        audio_bytes = self._post_speech(settings.speech_base_url, api_key, body)
        request.output_dir.mkdir(parents=True, exist_ok=True)
        file_path = request.output_dir / f"speech_{uuid4().hex[:8]}.wav"
        file_path.write_bytes(audio_bytes)
        duration_seconds = self._estimate_duration(request.text, request.speed)
        return SpeechResult(
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256=hashlib.sha256(audio_bytes).hexdigest(),
            content_type="audio/wav",
            provider=self.provider_name,
            model=model,
            duration_seconds=duration_seconds,
            alignment=build_word_alignment(request.text, duration_seconds),
        )

    def _speech_request_body(
        self,
        request: SpeechRequest,
        model: str,
        default_voice: str,
    ) -> dict[str, Any]:
        voice = request.voice_profile_id.strip() or default_voice
        return {
            "model": model,
            "voice": voice,
            "input": request.text,
            "speed": request.speed,
            "response_format": "wav",
        }

    def _post_speech(
        self,
        base_url: str,
        api_key: str,
        body: dict[str, Any],
    ) -> bytes:
        settings = get_settings()
        url = base_url.rstrip("/") + "/audio/speech"
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "audio/wav",
                "X-Correlation-ID": current_correlation_id() or "",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=settings.speech_timeout_seconds,
            ) as response:
                content: bytes = response.read()
                return content
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Speech provider HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Speech provider network error: {redact_secrets(str(exc.reason))}"
            ) from exc

    def _estimate_duration(self, text: str, speed: float) -> int:
        words = max(1, len(text.split()))
        words_per_second = max(1.0, 2.6 * speed)
        return max(1, int(round(words / words_per_second)))
