import json
import urllib.error
import urllib.request
from typing import Any

from app.config.provider_policy import provider_requires_api_key
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.llm.openai_compatible import (
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
        http_request = urllib.request.Request(
            url,
            data=request_payload,
            headers=headers,
            method="POST",
        )
        try:
            response = self._send_http_request(http_request, timeout_seconds)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                self._http_error_message(config, exc.code, detail, request.model)
            ) from exc
        content = self._extract_ollama_content(response)
        return {
            "model": str(response.get("model") or request.model),
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": int(response.get("prompt_eval_count") or 0),
                "completion_tokens": int(response.get("eval_count") or 0),
            },
        }

    def _extract_ollama_content(self, response: dict[str, Any]) -> str:
        if error := response.get("error"):
            raise RuntimeError(f"{self.display_name} retornou erro: {redact_secrets(error)}")
        message = response.get("message")
        if not isinstance(message, dict):
            raise RuntimeError(f"{self.display_name} retornou message fora do formato esperado")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(
                f"{self.display_name} retornou content vazio ou fora do formato esperado"
            )
        return content
