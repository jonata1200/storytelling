import asyncio
import json
import urllib.error
import urllib.request
from typing import Any

from app.config.provider_policy import ensure_provider_api_key, validate_model_name
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.llm.types import LLMRequest, LLMResult

OMNIROUTE_LLM_HTTP_TIMEOUT_SECONDS = 300
OMNIROUTE_LLM_MIN_HTTP_TIMEOUT_SECONDS = 15


class OmniRouteLLMProvider:
    provider_name = "omniroute"

    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        request = request.model_copy(
            update={"model": validate_model_name(request.model, provider=self.provider_name)}
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
            estimated_cost=str(usage.get("cost") or "0.000000"),
        )

    def _send_request(self, request: LLMRequest, use_response_format: bool) -> dict[str, Any]:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.omniroute_api_key,
            self.provider_name,
            "OMNIROUTE_API_KEY",
        )
        url = f"{settings.omniroute_base_url.rstrip('/')}/chat/completions"
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Você é um motor de produção audiovisual. "
                        "Responda somente com JSON válido, sem markdown."
                    ),
                },
                {"role": "user", "content": request.prompt},
            ],
            "temperature": 0.7,
            "stream": False,
        }
        if use_response_format:
            body["response_format"] = {"type": "json_object"}
        http_request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-Correlation-ID": current_correlation_id() or "",
            },
            method="POST",
        )
        try:
            timeout_seconds = self._request_timeout_seconds(request)
            with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
                raw_body = response.read()
                content_type = str(
                    getattr(response, "headers", {}).get("content-type", "")
                ).lower()
                if "text/event-stream" in content_type:
                    try:
                        parsed = self._parse_event_stream_response(raw_body)
                    except RuntimeError as exc:
                        if use_response_format and "stream sem conte" in str(exc).lower():
                            return self._send_request(request, False)
                        raise
                else:
                    parsed = json.loads(raw_body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if use_response_format and exc.code in {400, 422}:
                return self._send_request(request, False)
            raise RuntimeError(f"OmniRoute HTTP {exc.code}: {redact_secrets(detail)}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"OmniRoute network error: {redact_secrets(exc.reason)}"
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError("OmniRoute timeout ao aguardar resposta") from exc
        except OSError as exc:
            raise RuntimeError(f"OmniRoute connection error: {redact_secrets(exc)}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "OmniRoute retornou resposta HTTP que não é JSON válido"
            ) from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("OmniRoute retornou resposta fora do formato esperado")
        return parsed

    def _request_timeout_seconds(self, request: LLMRequest) -> float:
        if request.timeout_seconds is None:
            return OMNIROUTE_LLM_HTTP_TIMEOUT_SECONDS
        return max(
            OMNIROUTE_LLM_MIN_HTTP_TIMEOUT_SECONDS,
            min(OMNIROUTE_LLM_HTTP_TIMEOUT_SECONDS, float(request.timeout_seconds)),
        )

    def _parse_event_stream_response(self, raw_body: bytes) -> dict[str, Any]:
        content_parts: list[str] = []
        model = ""
        usage: dict[str, Any] = {}
        for raw_line in raw_body.decode("utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if not data or data == "[DONE]":
                continue
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError as exc:
                raise RuntimeError("OmniRoute retornou stream com JSON inválido") from exc
            if not isinstance(chunk, dict):
                continue
            if error := chunk.get("error"):
                raise RuntimeError(f"OmniRoute retornou erro: {redact_secrets(error)}")
            model = model or str(chunk.get("model") or "")
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            choices = chunk.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            first_choice = choices[0]
            if not isinstance(first_choice, dict):
                continue
            message = first_choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                content_parts.append(message["content"])
            delta = first_choice.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                content_parts.append(delta["content"])
        content = "".join(content_parts).strip()
        if not content:
            raise RuntimeError("OmniRoute retornou stream sem conteúdo")
        return {
            "model": model,
            "choices": [{"message": {"content": content}}],
            "usage": usage,
        }

    def _extract_message_content(self, response: dict[str, Any]) -> str:
        if error := response.get("error"):
            if isinstance(error, dict):
                message = error.get("message") or error.get("code") or error
            else:
                message = error
            raise RuntimeError(f"OmniRoute retornou erro: {redact_secrets(message)}")

        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            keys = ", ".join(sorted(response.keys())) or "nenhuma chave"
            raise RuntimeError(
                "OmniRoute retornou resposta sem choices. "
                f"Chaves recebidas: {keys}"
            )

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise RuntimeError("OmniRoute retornou choices fora do formato esperado")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("OmniRoute retornou message fora do formato esperado")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OmniRoute retornou content vazio ou fora do formato esperado")
        return content

    def _parse_json_content(self, content_text: str) -> dict[str, Any]:
        stripped = content_text.strip()
        if stripped.startswith("```"):
            stripped = stripped.removeprefix("```json").removeprefix("```").strip()
            stripped = stripped.removesuffix("```").strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OmniRoute retornou conteúdo que não é JSON válido") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("OmniRoute retornou JSON fora do formato esperado")
        return parsed
