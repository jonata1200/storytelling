import asyncio
import base64
import hashlib
import json
import urllib.error
import urllib.request
from typing import Any
from uuid import uuid4

from app.config.settings import get_settings
from app.providers.image.types import ImageEditRequest, ImageGenerationRequest, ImageResult
from app.providers.media_utils import extension_from_media_type, local_uri_to_data_url


class OpenRouterImageProvider:
    provider_name = "openrouter"

    async def generate(self, request: ImageGenerationRequest) -> ImageResult:
        response = await asyncio.to_thread(self._generate, request)
        return response

    async def edit(self, request: ImageEditRequest) -> ImageResult:
        generation_request = ImageGenerationRequest(
            prompt=request.prompt,
            target_id="edit",
            view_type="variant",
            output_dir=request.output_dir,
            references=[request.source_uri],
            model=request.model,
        )
        return await self.generate(generation_request)

    def _generate(self, request: ImageGenerationRequest) -> ImageResult:
        settings = get_settings()
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY nao configurada")

        prompt = request.prompt
        if request.negative_prompt:
            prompt = f"{prompt}\nEvite: {request.negative_prompt}"
        body: dict[str, Any] = {
            "model": request.model,
            "prompt": prompt,
            "n": 1,
            "aspect_ratio": request.aspect_ratio,
            "output_format": "png",
        }
        if request.references:
            body["input_references"] = [
                {
                    "type": "image_url",
                    "image_url": {"url": local_uri_to_data_url(reference)},
                }
                for reference in request.references
            ]

        response = self._post_json("/images", body)
        data = response.get("data")
        if not isinstance(data, list) or not data:
            raise RuntimeError("OpenRouter Images retornou resposta sem data")
        first_image = data[0]
        if not isinstance(first_image, dict):
            raise RuntimeError("OpenRouter Images retornou item fora do formato esperado")
        encoded_image = first_image.get("b64_json")
        if not isinstance(encoded_image, str) or not encoded_image:
            raise RuntimeError("OpenRouter Images nao retornou b64_json")

        media_type = str(first_image.get("media_type") or "image/png")
        image_bytes = base64.b64decode(encoded_image.encode("ascii"))
        request.output_dir.mkdir(parents=True, exist_ok=True)
        extension = extension_from_media_type(media_type)
        safe_view = request.view_type.replace("/", "_").replace("\\", "_")
        filename = f"{request.target_id}_{safe_view}_{uuid4().hex[:8]}{extension}"
        file_path = request.output_dir / filename
        file_path.write_bytes(image_bytes)
        sha256 = hashlib.sha256(image_bytes).hexdigest()
        raw_usage = response.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        return ImageResult(
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256=sha256,
            content_type=media_type,
            provider=self.provider_name,
            model=request.model,
            prompt=prompt,
            estimated_cost=str(usage.get("cost") or "0.000000"),
        )

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        url = f"{settings.openrouter_base_url.rstrip('/')}{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": settings.openrouter_site_url,
                "X-OpenRouter-Title": settings.openrouter_app_title,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenRouter Images HTTP {exc.code}: {detail}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("OpenRouter Images retornou resposta fora do formato esperado")
        if error := parsed.get("error"):
            raise RuntimeError(f"OpenRouter Images retornou erro: {error}")
        return parsed
