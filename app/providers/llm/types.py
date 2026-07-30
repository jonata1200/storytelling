from typing import Any, Protocol

from pydantic import BaseModel, Field


class LLMRequest(BaseModel):
    task: str
    prompt: str
    variables: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    model: str = "oc/deepseek-v4-flash-free"
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
    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        ...
