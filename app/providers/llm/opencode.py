import asyncio
import json
import urllib.error
import urllib.request
from typing import Any

from app.config.provider_policy import (
    ensure_provider_api_key,
    provider_api_key,
    provider_base_url,
    validate_model_name,
)
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.llm.omniroute import (
    OMNIROUTE_LLM_HTTP_TIMEOUT_SECONDS,
    OMNIROUTE_LLM_MIN_HTTP_TIMEOUT_SECONDS,
    OmniRouteLLMProvider,
)
from app.providers.llm.types import LLMRequest, LLMResult


class OpenCodeLLMProvider(OmniRouteLLMProvider):
    provider_name = "opencode"

    def _send_request(self, request: LLMRequest, use_response_format: bool) -> dict[str, Any]:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            provider_api_key(settings, self.provider_name),
            self.provider_name,
            "OPENCODE_API_KEY ou OMNIROUTE_API_KEY",
        )
        base_url = provider_base_url(settings, self.provider_name)
        if not base_url:
            raise ValueError("OPENCODE_BASE_URL ou OMNIROUTE_BASE_URL nao configurada.")
        url = f"{base_url.rstrip('/')}/chat/completions"
        body: dict[str, Any] = {
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
            "temperature": self._temperature_for_task(request.task),
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
            raise RuntimeError(f"OpenCode HTTP {exc.code}: {redact_secrets(detail)}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"OpenCode network error: {redact_secrets(exc.reason)}"
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError("OpenCode timeout ao aguardar resposta") from exc
        except OSError as exc:
            raise RuntimeError(f"OpenCode connection error: {redact_secrets(exc)}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "OpenCode retornou resposta HTTP que nao e JSON valido"
            ) from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("OpenCode retornou resposta fora do formato esperado")
        return parsed

    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        request = request.model_copy(
            update={"model": validate_model_name(request.model, provider=self.provider_name)}
        )
        response = await asyncio.to_thread(self._send_request, request, True)
        content_text = self._extract_message_content(response)
        content, recovery_strategy = self._parse_json_content(content_text, request.task)
        usage = response.get("usage", {})
        return LLMResult(
            content=content,
            model=str(response.get("model") or request.model),
            provider=self.provider_name,
            raw_content=content_text,
            recovery_strategy=recovery_strategy,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            estimated_cost=str(usage.get("cost") or "0.000000"),
        )

    def _request_timeout_seconds(self, request: LLMRequest) -> float:
        if request.timeout_seconds is None:
            return OMNIROUTE_LLM_HTTP_TIMEOUT_SECONDS
        return max(
            OMNIROUTE_LLM_MIN_HTTP_TIMEOUT_SECONDS,
            min(OMNIROUTE_LLM_HTTP_TIMEOUT_SECONDS, float(request.timeout_seconds)),
        )
