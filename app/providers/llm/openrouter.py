import asyncio
import json
import urllib.error
import urllib.request
from typing import Any

from app.config.settings import get_settings
from app.providers.llm.types import LLMRequest, LLMResult


class OpenRouterLLMProvider:
    provider_name = "openrouter"

    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        settings = get_settings()
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY nao configurada")

        response = await asyncio.to_thread(self._send_request, request)
        content_text = response["choices"][0]["message"]["content"]
        content = self._parse_json_content(content_text)
        usage = response.get("usage", {})
        return LLMResult(
            content=content,
            model=str(response.get("model") or request.model),
            provider=self.provider_name,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            estimated_cost="0.000000",
        )

    def _send_request(self, request: LLMRequest) -> dict[str, Any]:
        settings = get_settings()
        url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
        body = {
            "model": request.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Voce e um motor de producao audiovisual. "
                        "Responda somente com JSON valido, sem markdown."
                    ),
                },
                {"role": "user", "content": request.prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
        }
        data = json.dumps(body).encode("utf-8")
        http_request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": settings.openrouter_site_url,
                "X-OpenRouter-Title": settings.openrouter_app_title,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=120) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("OpenRouter retornou resposta fora do formato esperado")
        return parsed

    def _parse_json_content(self, content_text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenRouter retornou conteudo que nao e JSON valido") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("OpenRouter retornou JSON fora do formato esperado")
        return parsed
