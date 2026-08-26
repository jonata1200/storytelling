from decimal import Decimal
from typing import Any

from app.config.provider_policy import effective_provider_for_channel, provider_model
from app.config.settings import get_settings
from app.costs.service import estimate_operation_cost

SCRIPT_TEXT_ESTIMATED_TOKENS = Decimal("14000")
VISUAL_PROMPTS_ESTIMATED_TOKENS = Decimal("6000")


def model_provider_for_task(summary: dict[str, Any], task: str) -> tuple[str, str | None]:
    for setting in summary.get("model_settings", []):
        if str(getattr(setting, "task", "") or "") != task:
            continue
        provider = str(getattr(setting, "provider", "") or "").strip()
        model = str(getattr(setting, "model", "") or "").strip()
        if provider:
            return provider, model or None
    settings = get_settings()
    provider = effective_provider_for_channel(settings, "text")
    return provider, provider_model(settings, provider, "text")


def text_generation_cost_text(
    summary: dict[str, Any],
    task: str,
    estimated_tokens: Decimal,
    label: str,
) -> str:
    provider, model = model_provider_for_task(summary, task)
    estimate = estimate_operation_cost(
        "text_generation",
        estimated_tokens / Decimal("1000"),
        provider=provider,
        model=model,
    )
    return f"Estimativa: US$ {estimate.estimated} para {label}."


def operation_cost_text(
    operation: str,
    quantity: Decimal,
    *,
    provider: str,
    model: str | None,
    label: str,
) -> str:
    if quantity <= 0:
        return "Nenhum custo previsto agora."
    estimate = estimate_operation_cost(
        operation,
        quantity,
        provider=provider,
        model=model,
    )
    return f"Estimativa: US$ {estimate.estimated} para {label}."
