import asyncio
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import Message
from typing import Any

from app.config.provider_policy import ensure_provider_api_key, validate_model_name
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.llm.types import LLMRequest, LLMResult

OPENAI_COMPATIBLE_LLM_HTTP_TIMEOUT_SECONDS = 300
OPENAI_COMPATIBLE_LLM_MIN_HTTP_TIMEOUT_SECONDS = 15
OPENAI_COMPATIBLE_LLM_MAX_RETRY_ATTEMPTS = 3
OPENAI_COMPATIBLE_LLM_RETRY_DELAYS_SECONDS = (4.0, 12.0)
SCRIPT_TEXT_RECOVERY_TASKS = {"generate_script", "revise_script"}
DIRECTOR_CHAT_TEXT_RECOVERY_TASKS = {"director_agent_chat"}
TRANSIENT_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class OpenAICompatibleLLMConfig:
    provider_name: str
    display_name: str
    base_url: str
    api_key: str | None = None
    api_key_env: str | None = None
    require_api_key: bool = True
    allow_response_format_fallback: bool = True


def _raw_response_preview(value: str, limit: int = 800) -> str:
    return " ".join(str(value or "").split())[:limit]


class OpenAICompatibleResponseFormatError(RuntimeError):
    def __init__(
        self,
        message: str,
        raw_content: str = "",
        *,
        display_name: str = "Provider",
    ) -> None:
        self.raw_content = raw_content
        preview = _raw_response_preview(raw_content)
        detail = f"{message}. Previa da resposta: {preview}" if preview else message
        super().__init__(f"{display_name}: {detail}")


class OpenAICompatibleLLMProvider:
    provider_name = "openai_compatible"
    display_name = "OpenAI-compatible"

    def __init__(self, config: OpenAICompatibleLLMConfig | None = None) -> None:
        self._fixed_config = config

    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        config = self._provider_config()
        request = request.model_copy(
            update={"model": validate_model_name(request.model, provider=config.provider_name)}
        )
        response = await asyncio.to_thread(self._send_request, request, True)
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
        if self._fixed_config is None:
            raise NotImplementedError("Provider must define OpenAI-compatible config")
        return self._fixed_config

    def _send_request(self, request: LLMRequest, use_response_format: bool) -> dict[str, Any]:
        config = self._provider_config()
        api_key = self._api_key(config)
        url = f"{config.base_url.rstrip('/')}/chat/completions"
        # Iterativo com flag para evitar recursao infinita quando o fallback
        # sem response_format tambem retorna 400/422.
        attempted_without_format = not use_response_format
        current_use_format = use_response_format
        last_http_error: urllib.error.HTTPError | None = None
        last_http_detail = ""
        last_runtime_error: RuntimeError | None = None
        while True:
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
            if current_use_format:
                if request.output_schema:
                    body["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": request.task,
                            "strict": True,
                            "schema": request.output_schema,
                        },
                    }
                else:
                    body["response_format"] = {"type": "json_object"}

            headers = {
                "Content-Type": "application/json",
                "X-Correlation-ID": current_correlation_id() or "",
            }
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            request_payload = json.dumps(body).encode("utf-8")
            timeout_seconds = self._request_timeout_seconds(request)
            last_http_error = None
            last_http_detail = ""
            for attempt in range(OPENAI_COMPATIBLE_LLM_MAX_RETRY_ATTEMPTS):
                http_request = urllib.request.Request(
                    url,
                    data=request_payload,
                    headers=headers,
                    method="POST",
                )
                try:
                    parsed = self._send_http_request(http_request, timeout_seconds)
                except urllib.error.HTTPError as exc:
                    last_http_error = exc
                    detail = exc.read().decode("utf-8", errors="replace")
                    last_http_detail = detail
                    if (
                        current_use_format
                        and exc.code in {400, 422}
                        and not attempted_without_format
                        and config.allow_response_format_fallback
                    ):
                        attempted_without_format = True
                        current_use_format = False
                        break  # break retry loop, re-enter while True with new format
                    if self._should_retry_http_error(exc, detail, attempt):
                        self._sleep_before_retry(exc.headers, attempt)
                        continue
                    raise RuntimeError(
                        self._http_error_message(config, exc.code, detail, request.model)
                    ) from exc
                except RuntimeError as exc:
                    last_runtime_error = exc
                    if (
                        current_use_format
                        and not attempted_without_format
                        and "stream sem conte" in str(exc).lower()
                    ):
                        attempted_without_format = True
                        current_use_format = False
                        break  # break retry loop, re-enter while True with new format
                    if self._should_retry_runtime_error(exc, attempt):
                        self._sleep_before_retry(None, attempt)
                        continue
                    raise
                else:
                    if not isinstance(parsed, dict):
                        raise RuntimeError(
                            f"{config.display_name} retornou resposta fora do formato esperado"
                        )
                    return parsed
            else:
                # Retry loop exhausted without break — raise last error.
                if last_http_error is not None:
                    raise RuntimeError(
                        self._http_error_message(
                            config,
                            last_http_error.code,
                            last_http_detail,
                            request.model,
                        )
                    ) from last_http_error
                if last_runtime_error is not None:
                    raise last_runtime_error
                raise RuntimeError(f"{config.display_name} nao retornou resposta")
            # If we broke out of the retry loop to switch response_format, continue while loop.
            if current_use_format != use_response_format and attempted_without_format:
                continue
            if last_http_error is not None:
                raise RuntimeError(
                    self._http_error_message(
                        config,
                        last_http_error.code,
                        last_http_detail,
                        request.model,
                    )
                ) from last_http_error
            if last_runtime_error is not None:
                raise last_runtime_error
            raise RuntimeError(f"{config.display_name} nao retornou resposta")

    def _send_http_request(
        self,
        http_request: urllib.request.Request,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        try:
            with self._urlopen(http_request, timeout_seconds) as response:
                raw_body = response.read()
                content_type = str(
                    getattr(response, "headers", {}).get("content-type", "")
                ).lower()
                if "text/event-stream" in content_type:
                    try:
                        parsed = self._parse_event_stream_response(raw_body)
                    except RuntimeError:
                        raise
                else:
                    parsed = json.loads(raw_body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise exc
        except urllib.error.URLError as exc:
            config = self._provider_config()
            raise RuntimeError(self._network_error_message(config, exc.reason)) from exc
        except TimeoutError as exc:
            config = self._provider_config()
            raise RuntimeError(f"{config.display_name} timeout ao aguardar resposta") from exc
        except OSError as exc:
            config = self._provider_config()
            raise RuntimeError(
                f"{config.display_name} connection error: {redact_secrets(exc)}"
            ) from exc
        except json.JSONDecodeError as exc:
            config = self._provider_config()
            raise RuntimeError(
                f"{config.display_name} retornou resposta HTTP que nao e JSON valido"
            ) from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{config.display_name} retornou resposta fora do formato esperado")
        return parsed

    def _should_retry_http_error(
        self,
        exc: urllib.error.HTTPError,
        detail: str,
        attempt: int,
    ) -> bool:
        if attempt >= OPENAI_COMPATIBLE_LLM_MAX_RETRY_ATTEMPTS - 1:
            return False
        if exc.code not in TRANSIENT_HTTP_STATUS_CODES:
            return False
        lower_detail = detail.casefold()
        non_retryable_terms = ("invalid api key", "unauthorized", "forbidden")
        return not any(term in lower_detail for term in non_retryable_terms)

    def _should_retry_runtime_error(self, exc: RuntimeError, attempt: int) -> bool:
        if attempt >= OPENAI_COMPATIBLE_LLM_MAX_RETRY_ATTEMPTS - 1:
            return False
        message = str(exc).casefold()
        retryable_terms = (
            "timeout",
            "network",
            "connection",
            "temporarily unavailable",
            "temporary failure",
            "remote end closed",
        )
        return any(term in message for term in retryable_terms)

    def _sleep_before_retry(self, headers: Message | None, attempt: int) -> None:
        retry_after = self._retry_after_seconds(headers)
        delay = (
            retry_after
            if retry_after is not None
            else OPENAI_COMPATIBLE_LLM_RETRY_DELAYS_SECONDS[
                min(attempt, len(OPENAI_COMPATIBLE_LLM_RETRY_DELAYS_SECONDS) - 1)
            ]
        )
        time.sleep(delay)

    @staticmethod
    def _retry_after_seconds(headers: Message | None) -> float | None:
        if headers is None:
            return None
        raw_value = headers.get("Retry-After")
        if not raw_value:
            return None
        try:
            return max(0.0, min(60.0, float(raw_value)))
        except ValueError:
            return None

    def _http_error_message(
        self,
        config: OpenAICompatibleLLMConfig,
        status_code: int,
        detail: str,
        model: str,
    ) -> str:
        redacted_detail = redact_secrets(detail)
        model_detail = f" Modelo: {model}."
        lower_detail = str(detail).casefold()
        normalized_detail = re.sub(r"[^a-z]", "", lower_detail)
        if "resourceexhausted" in normalized_detail:
            return (
                f"{config.display_name} HTTP {status_code}: limite temporario de capacidade "
                f"atingido no provider. Tente novamente em alguns instantes ou escolha um "
                f"modelo menor/mais estavel.{model_detail} Detalhe: {redacted_detail}"
            )
        if status_code == 404 and (
            "not found for account" in lower_detail or "function" in lower_detail
        ):
            return (
                f"{config.display_name} HTTP 404: o modelo selecionado nao esta disponivel "
                f"para esta chave/conta do provider. Escolha outro modelo ou habilite o "
                f"modelo no painel do provider.{model_detail} Detalhe: {redacted_detail}"
            )
        return f"{config.display_name} HTTP {status_code}:{model_detail} {redacted_detail}"

    def _api_key(self, config: OpenAICompatibleLLMConfig) -> str | None:
        if config.require_api_key:
            return ensure_provider_api_key(
                config.api_key,
                config.provider_name,
                config.api_key_env,
            )
        return config.api_key

    def _urlopen(
        self,
        request: urllib.request.Request,
        timeout_seconds: float,
    ) -> Any:
        return urllib.request.urlopen(request, timeout=timeout_seconds)

    def _network_error_message(
        self,
        config: OpenAICompatibleLLMConfig,
        reason: object,
    ) -> str:
        detail = str(redact_secrets(reason))
        return f"{config.display_name} network error: {detail}"

    def _request_timeout_seconds(self, request: LLMRequest) -> float:
        if request.timeout_seconds is None:
            return OPENAI_COMPATIBLE_LLM_HTTP_TIMEOUT_SECONDS
        return max(
            OPENAI_COMPATIBLE_LLM_MIN_HTTP_TIMEOUT_SECONDS,
            min(OPENAI_COMPATIBLE_LLM_HTTP_TIMEOUT_SECONDS, float(request.timeout_seconds)),
        )

    def _parse_event_stream_response(self, raw_body: bytes) -> dict[str, Any]:
        config = self._provider_config()
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
                raise RuntimeError(
                    f"{config.display_name} retornou stream com JSON invalido"
                ) from exc
            if not isinstance(chunk, dict):
                continue
            if error := chunk.get("error"):
                raise RuntimeError(
                    f"{config.display_name} retornou erro: {redact_secrets(error)}"
                )
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
            raise RuntimeError(f"{config.display_name} retornou stream sem conteudo")
        return {
            "model": model,
            "choices": [{"message": {"content": content}}],
            "usage": usage,
        }

    def _extract_message_content(self, response: dict[str, Any]) -> str:
        config = self._provider_config()
        if error := response.get("error"):
            if isinstance(error, dict):
                message = error.get("message") or error.get("code") or error
            else:
                message = error
            raise RuntimeError(f"{config.display_name} retornou erro: {redact_secrets(message)}")

        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            keys = ", ".join(sorted(response.keys())) or "nenhuma chave"
            raise RuntimeError(
                f"{config.display_name} retornou resposta sem choices. "
                f"Chaves recebidas: {keys}"
            )

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise RuntimeError(f"{config.display_name} retornou choices fora do formato esperado")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError(f"{config.display_name} retornou message fora do formato esperado")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(
                f"{config.display_name} retornou content vazio ou fora do formato esperado"
            )
        return content

    def _temperature_for_task(self, task: str) -> float:
        if task in {"generate_script", "revise_script"}:
            return 0.4
        if task in {
            "generate_scenes_and_shots",
            "generate_storyboard_prompts",
        }:
            return 0.45
        return 0.7

    def _json_from_embedded_object(self, value: str) -> dict[str, Any] | None:
        decoder = json.JSONDecoder()
        for index, char in enumerate(value):
            if char != "{":
                continue
            try:
                parsed, _end = decoder.raw_decode(value[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _looks_like_screenplay_text(self, value: str) -> bool:
        text = str(value or "").strip().upper()
        if not text:
            return False
        return (
            "FADE IN" in text
            and "CENA" in text
            and any(marker in text for marker in ("INT.", "EXT.", "INT/EXT."))
        )

    def _parse_json_content(
        self,
        content_text: str,
        task: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        config = self._provider_config()
        stripped = content_text.strip()
        if stripped.startswith("```"):
            stripped = stripped.removeprefix("```json").removeprefix("```").strip()
            stripped = stripped.removesuffix("```").strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            embedded = self._json_from_embedded_object(stripped)
            if embedded is not None:
                return embedded, "embedded_json"
            if task in SCRIPT_TEXT_RECOVERY_TASKS and self._looks_like_screenplay_text(stripped):
                return {"content": stripped}, "screenplay_text"
            if task in DIRECTOR_CHAT_TEXT_RECOVERY_TASKS:
                # O chat livre do diretor pode responder em texto puro; embrulhe a
                # resposta em {"message": ...} em vez de falhar a geracao.
                return {"message": stripped}, "plain_text_message"
            raise OpenAICompatibleResponseFormatError(
                f"{config.display_name} retornou conteudo que nao e JSON valido",
                stripped,
                display_name=config.display_name,
            ) from exc
        if not isinstance(parsed, dict):
            if task in DIRECTOR_CHAT_TEXT_RECOVERY_TASKS:
                return {"message": stripped}, "plain_text_message"
            raise OpenAICompatibleResponseFormatError(
                f"{config.display_name} retornou JSON fora do formato esperado",
                stripped,
                display_name=config.display_name,
            )
        return parsed, None
