import json
import urllib.error
import urllib.request
from typing import Any

from app.config.provider_policy import provider_requires_api_key
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.llm.openai_compatible import (
    OPENAI_COMPATIBLE_LLM_MAX_RETRY_ATTEMPTS,
    OpenAICompatibleLLMConfig,
    OpenAICompatibleLLMProvider,
)
from app.providers.llm.types import LLMRequest


class OllamaCloudLLMProvider(OpenAICompatibleLLMProvider):
    provider_name = "ollama_cloud"
    display_name = "Ollama Cloud"

    def _provider_config(self) -> OpenAICompatibleLLMConfig:
        settings = get_settings()
        return OpenAICompatibleLLMConfig(
            provider_name=self.provider_name,
            display_name=self.display_name,
            base_url=settings.ollama_cloud_base_url,
            api_key=settings.ollama_cloud_api_key,
            api_key_env="OLLAMA_CLOUD_API_KEY",
            require_api_key=provider_requires_api_key(settings, self.provider_name),
        )

    def _send_request(self, request: LLMRequest, use_response_format: bool) -> dict[str, Any]:
        _ = use_response_format
        config = self._provider_config()
        api_key = self._api_key(config)
        url = f"{config.base_url.rstrip('/')}/chat"
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Voce e um motor de producao audiovisual. "
                        "Responda somente com JSON valido, sem markdown e sem texto fora "
                        "do objeto JSON."
                    ),
                },
                {"role": "user", "content": request.prompt},
            ],
            "stream": False,
            "options": {"temperature": self._temperature_for_task(request.task)},
        }
        headers = {
            "Content-Type": "application/json",
            "X-Correlation-ID": current_correlation_id() or "",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request_payload = json.dumps(body).encode("utf-8")
        timeout_seconds = self._request_timeout_seconds(request)
        last_http_error: urllib.error.HTTPError | None = None
        last_http_detail = ""
        for attempt in range(OPENAI_COMPATIBLE_LLM_MAX_RETRY_ATTEMPTS):
            http_request = urllib.request.Request(
                url,
                data=request_payload,
                headers=headers,
                method="POST",
            )
            try:
                response = self._send_http_request(http_request, timeout_seconds)
                content = self._extract_ollama_content(response)
            except urllib.error.HTTPError as exc:
                last_http_error = exc
                detail = exc.read().decode("utf-8", errors="replace")
                last_http_detail = detail
                if self._should_retry_http_error(exc, detail, attempt):
                    self._sleep_before_retry(exc.headers, attempt)
                    continue
                raise RuntimeError(
                    self._http_error_message(config, exc.code, detail, request.model)
                ) from exc
            except RuntimeError as exc:
                if self._should_retry_ollama_runtime_error(exc, attempt):
                    self._sleep_before_retry(None, attempt)
                    continue
                raise
            return {
                "model": str(response.get("model") or request.model),
                "choices": [{"message": {"content": content}}],
                "usage": {
                    "prompt_tokens": int(response.get("prompt_eval_count") or 0),
                    "completion_tokens": int(response.get("eval_count") or 0),
                },
            }

        if last_http_error is not None:
            raise RuntimeError(
                self._http_error_message(
                    config,
                    last_http_error.code,
                    last_http_detail,
                    request.model,
                )
            ) from last_http_error
        raise RuntimeError(f"{self.display_name} nao retornou resposta")

    def _should_retry_ollama_runtime_error(self, exc: RuntimeError, attempt: int) -> bool:
        if attempt >= OPENAI_COMPATIBLE_LLM_MAX_RETRY_ATTEMPTS - 1:
            return False
        message = str(exc).casefold()
        if "content vazio" in message:
            return True
        return self._should_retry_runtime_error(exc, attempt)

    def _extract_ollama_content(self, response: dict[str, Any]) -> str:
        if error := response.get("error"):
            raise RuntimeError(f"{self.display_name} retornou erro: {redact_secrets(error)}")
        message = response.get("message")
        if isinstance(message, dict):
            content = self._content_text(message.get("content"))
            if content:
                return content
        fallback_content = self._fallback_response_content(response)
        if fallback_content:
            return fallback_content
        if not isinstance(message, dict):
            raise RuntimeError(f"{self.display_name} retornou message fora do formato esperado")
        raise RuntimeError(
            f"{self.display_name} retornou content vazio ou fora do formato esperado"
        )

    def _fallback_response_content(self, response: dict[str, Any]) -> str:
        for key in ("response", "content"):
            content = self._content_text(response.get(key))
            if content:
                return content

        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    content = self._content_text(message.get("content"))
                    if content:
                        return content
                delta = first_choice.get("delta")
                if isinstance(delta, dict):
                    content = self._content_text(delta.get("content"))
                    if content:
                        return content
        return ""

    def _content_text(self, content: object) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                for key in ("text", "content"):
                    value = item.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                        break
            return "".join(parts).strip()
        return ""
