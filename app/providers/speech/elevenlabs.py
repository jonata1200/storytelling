import asyncio
import base64
import binascii
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.config.provider_policy import ensure_provider_api_key, validate_model_name
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.media_utils import extension_from_media_type
from app.providers.speech.types import SpeechRequest, SpeechResult
from app.storyboards.timeline import build_word_alignment


class ElevenLabsSpeechProvider:
    provider_name = "elevenlabs"
    display_name = "ElevenLabs Speech"

    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        return await asyncio.to_thread(self._synthesize, request)

    def _synthesize(self, request: SpeechRequest) -> SpeechResult:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.elevenlabs_api_key,
            self.provider_name,
            "ELEVENLABS_API_KEY",
        )
        model = validate_model_name(
            request.model or settings.elevenlabs_speech_model,
            provider=self.provider_name,
        )
        voice_id = self._voice_id(request.voice_profile_id, settings.elevenlabs_voice_id)
        body = self._speech_request_body(request, model)
        response = self._post_speech_with_timestamps(
            settings.elevenlabs_base_url,
            api_key,
            voice_id,
            settings.elevenlabs_output_format,
            body,
        )
        audio_bytes = self._audio_bytes(response)
        alignment = response.get("alignment") if isinstance(response.get("alignment"), dict) else {}
        duration_seconds = self._duration_seconds(alignment, request.text, request.speed)
        if not alignment:
            alignment = build_word_alignment(request.text, duration_seconds)

        request.output_dir.mkdir(parents=True, exist_ok=True)
        content_type = self._content_type(settings.elevenlabs_output_format)
        extension = extension_from_media_type(content_type)
        file_path = request.output_dir / f"speech_{uuid4().hex[:8]}{extension}"
        file_path.write_bytes(audio_bytes)
        return SpeechResult(
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256=hashlib.sha256(audio_bytes).hexdigest(),
            content_type=content_type,
            provider=self.provider_name,
            model=model,
            duration_seconds=duration_seconds,
            alignment=alignment,
            estimated_cost=self._estimated_cost(request.text, model),
        )

    @staticmethod
    def _voice_id(voice_profile_id: str, default_voice_id: str) -> str:
        voice_id = str(voice_profile_id or "").strip() or str(default_voice_id or "").strip()
        if not voice_id:
            raise ValueError("ELEVENLABS_VOICE_ID não configurada para geração de voz")
        return voice_id

    @staticmethod
    def _speech_request_body(request: SpeechRequest, model: str) -> dict[str, Any]:
        return {
            "text": request.text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.25 if request.emotion else 0,
                "use_speaker_boost": True,
            },
        }

    def _post_speech_with_timestamps(
        self,
        base_url: str,
        api_key: str,
        voice_id: str,
        output_format: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        encoded_voice_id = urllib.parse.quote(voice_id, safe="")
        query = urllib.parse.urlencode({"output_format": output_format})
        url = f"{base_url.rstrip('/')}/text-to-speech/{encoded_voice_id}/with-timestamps?{query}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "xi-api-key": api_key,
                "X-Correlation-ID": current_correlation_id() or "",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=get_settings().speech_timeout_seconds,
            ) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{self.display_name} HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"{self.display_name} network error: {redact_secrets(str(exc.reason))}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{self.display_name} retornou JSON invalido") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{self.display_name} retornou resposta fora do formato esperado")
        return parsed

    def _audio_bytes(self, response: dict[str, Any]) -> bytes:
        encoded = response.get("audio_base64") or response.get("audio")
        if not isinstance(encoded, str) or not encoded.strip():
            raise RuntimeError(f"{self.display_name} não retornou audio_base64")
        try:
            return base64.b64decode(encoded.encode("ascii"), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError(f"{self.display_name} retornou audio base64 invalido") from exc

    def _duration_seconds(self, alignment: object, text: str, speed: float) -> int:
        if isinstance(alignment, dict):
            end_times = alignment.get("character_end_times_seconds")
            if isinstance(end_times, list) and end_times:
                try:
                    return max(1, int(round(max(float(value) for value in end_times))))
                except (TypeError, ValueError):
                    pass
        return self._estimate_duration(text, speed)

    @staticmethod
    def _estimate_duration(text: str, speed: float) -> int:
        words = max(1, len(text.split()))
        words_per_second = max(1.0, 2.6 * speed)
        return max(1, int(round(words / words_per_second)))

    @staticmethod
    def _content_type(output_format: str) -> str:
        normalized = str(output_format or "").strip().lower()
        if normalized.startswith("wav"):
            return "audio/wav"
        if normalized.startswith("pcm"):
            return "audio/wav"
        if normalized.startswith("ogg"):
            return "audio/ogg"
        return "audio/mpeg"

    @staticmethod
    def _estimated_cost(text: str, model: str) -> str:
        rate = Decimal("0.050000") if "flash" in model or "turbo" in model else Decimal("0.100000")
        quantity = Decimal(max(1, len(text))) / Decimal("1000")
        return str((quantity * rate).quantize(Decimal("0.000001")))
