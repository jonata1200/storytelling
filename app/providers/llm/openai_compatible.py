import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.config.provider_policy import ensure_provider_api_key, validate_model_name
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.llm.types import LLMRequest, LLMResult

OPENAI_COMPATIBLE_LLM_HTTP_TIMEOUT_SECONDS = 300
OPENAI_COMPATIBLE_LLM_MIN_HTTP_TIMEOUT_SECONDS = 15
SCRIPT_TEXT_RECOVERY_TASKS = {"generate_script", "revise_script"}


@dataclass(frozen=True)
class OpenAICompatibleLLMConfig:
    provider_name: str
    display_name: str
    base_url: str
    api_key: str | None = None
    api_key_env: str | None = None
    require_api_key: bool = True


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
        super().__init__(detail.replace("Provider", display_name, 1))


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

        headers = {
            "Content-Type": "application/json",
            "X-Correlation-ID": current_correlation_id() or "",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        http_request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            timeout_seconds = self._request_timeout_seconds(request)
            with self._urlopen(http_request, timeout_seconds) as response:
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
            raise RuntimeError(
                f"{config.display_name} HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(self._network_error_message(config, exc.reason)) from exc
        except TimeoutError as exc:
            raise RuntimeError(f"{config.display_name} timeout ao aguardar resposta") from exc
        except OSError as exc:
            raise RuntimeError(
                f"{config.display_name} connection error: {redact_secrets(exc)}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{config.display_name} retornou resposta HTTP que nao e JSON valido"
            ) from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{config.display_name} retornou resposta fora do formato esperado")
        return parsed

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
            "generate_visual_bible",
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
            raise OpenAICompatibleResponseFormatError(
                f"{config.display_name} retornou conteudo que nao e JSON valido",
                stripped,
                display_name=config.display_name,
            ) from exc
        if not isinstance(parsed, dict):
            raise OpenAICompatibleResponseFormatError(
                f"{config.display_name} retornou JSON fora do formato esperado",
                stripped,
                display_name=config.display_name,
            )
        return parsed, None
