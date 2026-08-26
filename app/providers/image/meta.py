import asyncio
import base64
import hashlib
import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from uuid import uuid4

from app.config.provider_policy import ensure_provider_api_key, provider_integration_mode
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.image.types import (
    ImageGenerationRequest,
    ImageGenerationResult,
)
from app.providers.llm.openai_compatible import TRANSIENT_HTTP_STATUS_CODES
from app.providers.media_utils import local_uri_to_data_url

META_IMAGE_MAX_ATTEMPTS = 3
META_IMAGE_RETRY_DELAYS_SECONDS = (2.0, 6.0)


class MetaImageProvider:
    provider_name = "meta"
    display_name = "Meta Muse Image"

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        return await asyncio.to_thread(self._generate, request)

    def _generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        settings = get_settings()
        mode = provider_integration_mode(settings, self.provider_name, "image")
        if mode != "api":
            raise ValueError(
                "Meta Image em modo browser ainda não está autorizado/implementado. "
                "Use META_IMAGE_INTEGRATION_MODE=api somente com endpoint oficial."
            )
        endpoint = str(settings.meta_image_endpoint or "").strip()
        if not endpoint:
            raise ValueError(
                "META_IMAGE_ENDPOINT não configurado. Informe apenas um endpoint oficial "
                "disponibilizado para a conta; endpoints privados não são aceitos."
            )
        api_key = ensure_provider_api_key(settings.meta_api_key, "meta", "META_API_KEY")
        body = {
            "model": request.model,
            "prompt": request.prompt,
            "aspect_ratio": request.aspect_ratio,
            "references": [
                {
                    "image_url": self._reference_data_url(reference.uri),
                    "role": reference.role,
                    "weight": reference.weight,
                    "metadata": reference.metadata,
                }
                for reference in request.references
            ],
            "metadata": request.metadata,
            "response_format": "b64_json",
        }
        payload = json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Correlation-ID": current_correlation_id() or "",
        }
        response = self._post_with_retry(
            endpoint,
            payload,
            headers,
            float(settings.meta_image_timeout_seconds),
        )
        image_bytes, content_type, external_metadata = self._image_payload(
            response,
            endpoint=endpoint,
            allowed_download_hosts=str(settings.meta_image_download_hosts or ""),
            timeout_seconds=float(settings.meta_image_timeout_seconds),
        )
        if not image_bytes:
            raise RuntimeError("Meta Muse Image retornou um arquivo de imagem vazio")
        if len(image_bytes) > int(settings.max_generated_asset_bytes):
            raise RuntimeError("Meta Muse Image retornou arquivo acima do limite permitido")
        detected_type, extension = self._detect_image_type(image_bytes, content_type)
        request.output_dir.mkdir(parents=True, exist_ok=True)
        file_path = request.output_dir / f"{uuid4().hex}{extension}"
        file_path.write_bytes(image_bytes)
        sha256 = hashlib.sha256(image_bytes).hexdigest()
        usage: dict[str, Any] = response["usage"] if isinstance(response.get("usage"), dict) else {}
        return ImageGenerationResult(
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256=sha256,
            content_type=detected_type,
            provider=self.provider_name,
            model=str(response.get("model") or request.model),
            prompt=request.prompt,
            external_job_id=str(response.get("id") or external_metadata.get("generation_id") or ""),
            estimated_cost=str(usage.get("cost") or "0.000000"),
            metadata=external_metadata,
        )

    def _post_with_retry(
        self,
        endpoint: str,
        payload: bytes,
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(META_IMAGE_MAX_ATTEMPTS):
            request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
            try:
                return self._read_json(request, timeout_seconds)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code not in TRANSIENT_HTTP_STATUS_CODES or attempt == (
                    META_IMAGE_MAX_ATTEMPTS - 1
                ):
                    raise RuntimeError(
                        f"{self.display_name} HTTP {exc.code}: {redact_secrets(detail)}"
                    ) from exc
                last_error = exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == META_IMAGE_MAX_ATTEMPTS - 1:
                    raise RuntimeError(
                        f"{self.display_name} indisponível: {redact_secrets(exc)}"
                    ) from exc
                last_error = exc
            time.sleep(META_IMAGE_RETRY_DELAYS_SECONDS[min(attempt, 1)])
        raise RuntimeError(f"{self.display_name} indisponível: {redact_secrets(last_error)}")

    def _read_json(self, request: urllib.request.Request, timeout_seconds: float) -> dict[str, Any]:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"{self.display_name} retornou resposta inválida")
        return payload

    def _image_payload(
        self,
        response: dict[str, Any],
        *,
        endpoint: str,
        allowed_download_hosts: str,
        timeout_seconds: float,
    ) -> tuple[bytes, str, dict[str, Any]]:
        items = response.get("data")
        item = items[0] if isinstance(items, list) and items else response.get("image")
        if not isinstance(item, dict):
            raise RuntimeError(f"{self.display_name} não retornou imagem")
        metadata = {
            key: value for key, value in item.items() if key not in {"b64_json", "base64", "url"}
        }
        encoded = item.get("b64_json") or item.get("base64")
        if isinstance(encoded, str) and encoded:
            try:
                return (
                    base64.b64decode(encoded, validate=True),
                    str(item.get("content_type") or ""),
                    metadata,
                )
            except ValueError as exc:
                raise RuntimeError(f"{self.display_name} retornou base64 inválido") from exc
        url = str(item.get("url") or "").strip()
        if not url:
            raise RuntimeError(f"{self.display_name} não retornou arquivo original")
        self._validate_download_url(url, endpoint, allowed_download_hosts)
        with urllib.request.urlopen(url, timeout=timeout_seconds) as download:
            content_type = str(download.headers.get("content-type", ""))
            return download.read(), content_type, metadata

    @staticmethod
    def _validate_download_url(url: str, endpoint: str, configured_hosts: str) -> None:
        parsed = urllib.parse.urlparse(url)
        endpoint_host = urllib.parse.urlparse(endpoint).hostname or ""
        allowed = {host.strip().casefold() for host in configured_hosts.split(",") if host.strip()}
        if endpoint_host:
            allowed.add(endpoint_host.casefold())
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname.casefold() not in allowed
        ):
            raise RuntimeError("URL de download da imagem fora da allowlist HTTPS")

    @staticmethod
    def _reference_data_url(uri: str) -> str:
        if uri.startswith("data:image/"):
            return uri
        data_url = local_uri_to_data_url(uri)
        if not data_url:
            raise ValueError("Referência visual deve apontar para imagem local dentro do storage")
        return data_url

    @staticmethod
    def _detect_image_type(payload: bytes, declared: str) -> tuple[str, str]:
        if payload.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", ".png"
        if payload.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", ".jpg"
        if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
            return "image/webp", ".webp"
        guessed_extension = mimetypes.guess_extension(declared.split(";", 1)[0])
        if declared.startswith("image/") and guessed_extension:
            return declared.split(";", 1)[0], guessed_extension
        raise RuntimeError("Meta Muse Image retornou conteúdo que não é uma imagem suportada")
