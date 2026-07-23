import asyncio
import json
import urllib.error
import urllib.request
from typing import Any

from app.config.model_policy import validate_openrouter_model_name
from app.config.settings import get_settings, normalize_openrouter_api_key
from app.providers.llm.types import LLMRequest, LLMResult

OPENROUTER_LLM_HTTP_TIMEOUT_SECONDS = 300


class OpenRouterLLMProvider:
    provider_name = "openrouter"

    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        settings = get_settings()
        if not normalize_openrouter_api_key(settings.openrouter_api_key):
            raise RuntimeError("OPENROUTER_API_KEY ausente ou invalida")
        request = request.model_copy(
            update={"model": validate_openrouter_model_name(request.model)}
        )

        response = await asyncio.to_thread(self._send_request, request, True)
        content_text = self._extract_message_content(response)
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

    def _send_request(self, request: LLMRequest, use_response_format: bool) -> dict[str, Any]:
        settings = get_settings()
        api_key = normalize_openrouter_api_key(settings.openrouter_api_key)
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY ausente ou invalida")
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
            "temperature": 0.7,
        }
        if use_response_format:
            body["response_format"] = {"type": "json_object"}
        data = json.dumps(body).encode("utf-8")
        http_request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": settings.openrouter_site_url,
                "X-OpenRouter-Title": settings.openrouter_app_title,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request, timeout=OPENROUTER_LLM_HTTP_TIMEOUT_SECONDS
            ) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if use_response_format and exc.code in {400, 422}:
                return self._send_request(request, False)
            raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenRouter network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("OpenRouter timeout ao aguardar resposta") from exc
        except OSError as exc:
            raise RuntimeError(f"OpenRouter connection error: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenRouter retornou resposta HTTP que nao e JSON valido") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("OpenRouter retornou resposta fora do formato esperado")
        return parsed

    def _extract_message_content(self, response: dict[str, Any]) -> str:
        if error := response.get("error"):
            if isinstance(error, dict):
                message = error.get("message") or error.get("code") or error
            else:
                message = error
            raise RuntimeError(f"OpenRouter retornou erro: {message}")

        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            keys = ", ".join(sorted(response.keys())) or "nenhuma chave"
            raise RuntimeError(
                "OpenRouter retornou resposta sem choices. "
                f"Chaves recebidas: {keys}"
            )

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise RuntimeError("OpenRouter retornou choices fora do formato esperado")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("OpenRouter retornou message fora do formato esperado")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenRouter retornou content vazio ou fora do formato esperado")
        return content

    def _parse_json_content(self, content_text: str) -> dict[str, Any]:
        stripped = content_text.strip()
        if stripped.startswith("```"):
            stripped = stripped.removeprefix("```json").removeprefix("```").strip()
            stripped = stripped.removesuffix("```").strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenRouter retornou conteudo que nao e JSON valido") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("OpenRouter retornou JSON fora do formato esperado")
        return parsed
