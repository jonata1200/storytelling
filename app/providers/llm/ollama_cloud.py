import asyncio
import json
import re
import urllib.error
import urllib.request
from typing import Any

from app.config.provider_policy import ensure_provider_api_key, provider_integration_mode
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.llm.types import LLMRequest, LLMResponseFormatError, LLMResult


class OllamaCloudLLMProvider:
    """Adapter para a API nativa oficial do Ollama Cloud."""

    provider_name = "ollama_cloud"
    display_name = "Ollama Cloud"

    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        return await asyncio.to_thread(self._generate_structured, request)

    def _generate_structured(self, request: LLMRequest) -> LLMResult:
        settings = get_settings()
        if provider_integration_mode(settings, self.provider_name, "text") != "api":
            raise ValueError("Ollama Cloud requer OLLAMA_CLOUD_INTEGRATION_MODE=api")
        api_key = ensure_provider_api_key(
            settings.ollama_cloud_api_key,
            self.provider_name,
            "OLLAMA_API_KEY",
        )
        base_url = str(settings.ollama_cloud_base_url or "").rstrip("/")
        if not base_url:
            raise ValueError("OLLAMA_CLOUD_BASE_URL não configurada")
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Responda somente com JSON válido, sem markdown.",
                },
                {"role": "user", "content": request.prompt},
            ],
            "stream": False,
            "format": request.output_schema or "json",
            "options": {"temperature": self._temperature(request.task)},
        }
        http_request = urllib.request.Request(
            f"{base_url}/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-Correlation-ID": current_correlation_id() or "",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request, timeout=float(request.timeout_seconds or 180)
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Ollama Cloud HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Ollama Cloud indisponível: {redact_secrets(exc)}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama Cloud retornou resposta HTTP inválida") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Ollama Cloud retornou resposta fora do formato esperado")
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            error = payload.get("error")
            raise RuntimeError(f"Ollama Cloud retornou conteúdo vazio: {redact_secrets(error)}")
        parsed = _parse_json_content(content)
        if parsed is None:
            raise LLMResponseFormatError(
                "Ollama Cloud retornou conteúdo que não é JSON válido",
                content,
                display_name=self.display_name,
            )
        if not isinstance(parsed, dict):
            raise LLMResponseFormatError(
                "Ollama Cloud retornou JSON fora do formato esperado",
                content,
                display_name=self.display_name,
            )
        prompt_tokens = int(payload.get("prompt_eval_count") or 0)
        completion_tokens = int(payload.get("eval_count") or 0)
        estimated_cost = _estimate_text_cost(prompt_tokens + completion_tokens)
        return LLMResult(
            content=parsed,
            model=str(payload.get("model") or request.model),
            provider=self.provider_name,
            raw_content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost=estimated_cost,
        )

    @staticmethod
    def _temperature(task: str) -> float:
        return 0.4 if task in {"generate_script", "revise_script"} else 0.7


def _parse_json_content(content: str) -> Any | None:
    """Extrai um objeto JSON válido do conteúdo retornado pelo modelo.

    Alguns modelos do Ollama Cloud ignoram ``format: json`` e embrulham a
    resposta em fences markdown (`` ```json ... ``` ``) ou acrescentam texto
    antes/depois do objeto. Esta função tenta, em ordem:

    1. ``json.loads`` direto (caso comum — gemma4 respeita o format).
    2. Remover fences markdown e tentar de novo.
    3. Localizar o primeiro objeto JSON balanceado no texto (fallback para
       modelos que adicionam prosa ao redor do JSON).
    """
    text = content.strip()
    if not text:
        return None

    # 1. JSON puro.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Remove fences markdown (```json ... ``` ou ``` ... ```).
    fenced = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    fenced = re.sub(r"\s*```$", "", fenced).strip()
    if fenced:
        try:
            return json.loads(fenced)
        except json.JSONDecodeError:
            pass

    # 3. Localiza o primeiro objeto JSON balanceado no texto.
    return _extract_first_json_object(text)


def _extract_first_json_object(text: str) -> Any | None:
    """Retorna o primeiro objeto/array JSON balanceado encontrado no texto."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, (dict, list)):
            return value
    return None


def _estimate_text_cost(total_tokens: int) -> str:
    """Estima o custo de texto a partir dos tokens retornados pelo provider.

    Usa a política de custo de texto da aplicação (USD por 1k tokens). Quando o
    provider não reporta contagem de tokens, retorna zero (não inventa custo).
    """
    if total_tokens <= 0:
        return "0.000000"
    from decimal import ROUND_HALF_UP, Decimal

    from app.costs.service import DEFAULT_OPERATION_COSTS_USD

    _unit, unit_cost = DEFAULT_OPERATION_COSTS_USD["text_generation"]
    cost = (Decimal(total_tokens) / Decimal("1000")) * unit_cost
    return str(cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
