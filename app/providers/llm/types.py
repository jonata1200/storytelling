from typing import Any, Protocol

from pydantic import BaseModel, Field


def _raw_response_preview(value: str, limit: int = 800) -> str:
    return " ".join(str(value or "").split())[:limit]


class LLMResponseFormatError(RuntimeError):
    """Erro de formato de resposta de um provider de LLM."""

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


# Alias legado mantido para compatibilidade de imports externos.
OpenAICompatibleResponseFormatError = LLMResponseFormatError


class LLMRequest(BaseModel):
    task: str
    prompt: str
    variables: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    model: str = "opencode-zen/deepseek-v4-flash"
    timeout_seconds: float | None = None


class LLMResult(BaseModel):
    content: dict[str, Any]
    model: str
    provider: str
    raw_content: str | None = None
    recovery_strategy: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost: str = "0.000000"


class LLMProvider(Protocol):
    async def generate_structured(self, request: LLMRequest) -> LLMResult: ...
