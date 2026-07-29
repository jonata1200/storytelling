from typing import Any, Protocol

from pydantic import BaseModel, Field


class LLMRequest(BaseModel):
    task: str
    prompt: str
    variables: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    model: str = "ds-web/deepseek-v4-flash"


class LLMResult(BaseModel):
    content: dict[str, Any]
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost: str = "0.000000"


class LLMProvider(Protocol):
    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        ...
