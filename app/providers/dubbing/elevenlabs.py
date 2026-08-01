import json
import mimetypes
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from app.config.provider_policy import ensure_provider_api_key
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.dubbing.types import (
    DubbingDownloadResult,
    DubbingStatusResult,
    DubbingSubmitRequest,
    DubbingSubmitResult,
)


class ElevenLabsDubbingProvider:
    provider_name = "elevenlabs"
    display_name = "ElevenLabs Dubbing"

    def submit(self, request: DubbingSubmitRequest) -> DubbingSubmitResult:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.elevenlabs_api_key,
            self.provider_name,
            "ELEVENLABS_API_KEY",
        )
        fields = {
            "name": request.name,
            "target_lang": request.target_language,
        }
        if request.source_language:
            fields["source_lang"] = request.source_language
        body, content_type = self._multipart_body(
            fields,
            "file",
            request.file_path,
        )
        response = self._send_json(
            f"{settings.elevenlabs_base_url.rstrip('/')}/dubbing",
            api_key,
            method="POST",
            data=body,
            content_type=content_type,
        )
        external_job_id = response.get("dubbing_id")
        if not isinstance(external_job_id, str) or not external_job_id.strip():
            raise RuntimeError(f"{self.display_name} não retornou dubbing_id")
        expected = response.get("expected_duration_sec")
        expected_duration = float(expected) if isinstance(expected, int | float) else None
        return DubbingSubmitResult(
            external_job_id=external_job_id,
            expected_duration_seconds=expected_duration,
            metadata=response,
        )

    def status(self, external_job_id: str) -> DubbingStatusResult:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.elevenlabs_api_key,
            self.provider_name,
            "ELEVENLABS_API_KEY",
        )
        encoded_id = urllib.parse.quote(external_job_id, safe="")
        response = self._send_json(
            f"{settings.elevenlabs_base_url.rstrip('/')}/dubbing/{encoded_id}",
            api_key,
            method="GET",
        )
        status = str(response.get("status") or "unknown")
        target_languages = response.get("target_languages")
        return DubbingStatusResult(
            external_job_id=external_job_id,
            status=status,
            source_language=(
                str(response.get("source_language"))
                if response.get("source_language") is not None
                else None
            ),
            target_languages=[
                str(language) for language in target_languages if isinstance(language, str)
            ]
            if isinstance(target_languages, list)
            else [],
            error=str(response.get("error")) if response.get("error") else None,
            metadata=response,
        )

    def download(self, external_job_id: str, language_code: str) -> DubbingDownloadResult:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.elevenlabs_api_key,
            self.provider_name,
            "ELEVENLABS_API_KEY",
        )
        encoded_id = urllib.parse.quote(external_job_id, safe="")
        encoded_language = urllib.parse.quote(language_code, safe="")
        url = (
            f"{settings.elevenlabs_base_url.rstrip('/')}/dubbing/"
            f"{encoded_id}/audio/{encoded_language}"
        )
        request = urllib.request.Request(
            url,
            headers={
                "xi-api-key": api_key,
                "X-Correlation-ID": current_correlation_id() or "",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=settings.dubbing_poll_timeout_seconds,
            ) as response:
                content: bytes = response.read()
                content_type = response.headers.get_content_type() or "video/mp4"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{self.display_name} download HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"{self.display_name} download network error: {redact_secrets(str(exc.reason))}"
            ) from exc
        return DubbingDownloadResult(
            content=content,
            content_type=content_type,
            metadata={"language_code": language_code},
        )

    def _send_json(
        self,
        url: str,
        api_key: str,
        *,
        method: str,
        data: bytes | None = None,
        content_type: str = "application/json",
    ) -> dict[str, Any]:
        headers = {
            "xi-api-key": api_key,
            "X-Correlation-ID": current_correlation_id() or "",
        }
        if data is not None:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(
                request,
                timeout=get_settings().dubbing_poll_timeout_seconds,
            ) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{self.display_name} {method} HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"{self.display_name} {method} network error: {redact_secrets(str(exc.reason))}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{self.display_name} retornou JSON invalido") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{self.display_name} retornou resposta fora do formato esperado")
        return parsed

    @staticmethod
    def _multipart_body(
        fields: dict[str, str],
        file_field: str,
        file_path: Path,
    ) -> tuple[bytes, str]:
        boundary = f"----storytelling-{secrets.token_hex(16)}"
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                    str(value).encode(),
                    b"\r\n",
                ]
            )
        media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{file_field}"; '
                    f'filename="{file_path.name}"\r\n'
                ).encode(),
                f"Content-Type: {media_type}\r\n\r\n".encode(),
                file_path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
