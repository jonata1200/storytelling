import asyncio
import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from app.config.provider_policy import is_ollama_cloud_base_url, validate_model_name
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.llm.openai_compatible import (
    OpenAICompatibleLLMConfig,
    OpenAICompatibleLLMProvider,
)
from app.providers.llm.types import LLMRequest, LLMResult


class OllamaLLMProvider(OpenAICompatibleLLMProvider):
    provider_name = "ollama"
    display_name = "Ollama"

    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        config = self._provider_config()
        if not is_ollama_cloud_base_url(config.base_url):
            return await super().generate_structured(request)

        request = request.model_copy(
            update={"model": validate_model_name(request.model, provider=config.provider_name)}
        )
        response = await asyncio.to_thread(self._send_native_request, request, True)
        content_text = self._extract_message_content(response)
        content, recovery_strategy = self._parse_json_content(content_text, request.task)
        usage = response.get("usage", {})
        return LLMResult(
            content=content,
            model=str(response.get("model") or request.model),
            provider=config.provider_name,
            raw_content=content_text,
            recovery_strategy=recovery_strategy,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            estimated_cost=str(usage.get("cost") or "0.000000"),
        )

    def _provider_config(self) -> OpenAICompatibleLLMConfig:
        settings = get_settings()
        is_cloud = is_ollama_cloud_base_url(settings.ollama_base_url)
        return OpenAICompatibleLLMConfig(
            provider_name=self.provider_name,
            display_name=self.display_name,
            base_url=settings.ollama_base_url,
            api_key=settings.ollama_api_key if is_cloud else settings.ollama_api_key or "ollama",
            api_key_env="OLLAMA_API_KEY",
            require_api_key=is_cloud,
        )

    def _send_native_request(
        self,
        request: LLMRequest,
        use_response_format: bool,
    ) -> dict[str, Any]:
        config = self._provider_config()
        api_key = self._api_key(config)
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
            "options": {"temperature": self._temperature_for_task(request.task)},
            "stream": False,
        }
        if use_response_format:
            body["format"] = "json"

        headers = {
            "Content-Type": "application/json",
            "X-Correlation-ID": current_correlation_id() or "",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        http_request = urllib.request.Request(
            self._native_chat_url(config),
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            timeout_seconds = self._request_timeout_seconds(request)
            with self._urlopen(http_request, timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if use_response_format and exc.code in {400, 422}:
                return self._send_native_request(request, False)
            raise RuntimeError(
                f"{config.display_name} Cloud HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"{config.display_name} Cloud network error: {redact_secrets(exc.reason)}"
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError(f"{config.display_name} Cloud timeout ao aguardar resposta") from exc
        except OSError as exc:
            raise RuntimeError(
                f"{config.display_name} Cloud connection error: {redact_secrets(exc)}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{config.display_name} Cloud retornou resposta HTTP que nao e JSON valido"
            ) from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(
                f"{config.display_name} Cloud retornou resposta fora do formato esperado"
            )
        return self._native_response_to_openai_shape(parsed, request)

    def _native_chat_url(self, config: OpenAICompatibleLLMConfig) -> str:
        base_url = config.base_url.rstrip("/")
        path = urlparse(base_url).path.rstrip("/")
        if path.endswith("/api/chat"):
            return base_url
        if path.endswith("/api"):
            return f"{base_url}/chat"
        return f"{base_url}/api/chat"

    def _native_response_to_openai_shape(
        self,
        parsed: dict[str, Any],
        request: LLMRequest,
    ) -> dict[str, Any]:
        if error := parsed.get("error"):
            raise RuntimeError(f"{self.display_name} Cloud retornou erro: {redact_secrets(error)}")
        content = self._native_message_content(parsed)
        usage = {
            "prompt_tokens": int(parsed.get("prompt_eval_count") or 0),
            "completion_tokens": int(parsed.get("eval_count") or 0),
        }
        return {
            "model": parsed.get("model") or request.model,
            "choices": [{"message": {"content": content}}],
            "usage": usage,
        }

    def _native_message_content(self, parsed: dict[str, Any]) -> str:
        message = parsed.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, dict):
                return json.dumps(content)
        response = parsed.get("response")
        if isinstance(response, str) and response.strip():
            return response
        keys = ", ".join(sorted(parsed.keys())) or "nenhuma chave"
        raise RuntimeError(
            f"{self.display_name} Cloud retornou resposta sem conteudo. "
            f"Chaves recebidas: {keys}"
        )
