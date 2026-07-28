from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CostEntryType
from app.costs.models import CostEntry
from app.costs.schemas import (
    BudgetCheckRead,
    CostBreakdownItemRead,
    CostBudgetRead,
    CostBudgetUpdate,
    CostEntryCreate,
    OperationCostEstimateRead,
    OperationCostPolicyRead,
    ProjectCostSummaryRead,
)
from app.production.service import get_or_create_production_settings
from app.projects.repository import ProjectRepository


class CostBudgetExceededError(ValueError):
    def __init__(self, check: BudgetCheckRead) -> None:
        self.check = check
        limit = check.limit if check.limit is not None else Decimal("0.000000")
        super().__init__(
            "Estimativa de custo excede o limite configurado "
            f"({check.projected_cost} > {limit} USD)"
        )


DEFAULT_OPERATION_COSTS_USD: dict[str, tuple[str, Decimal]] = {
    "text_generation": ("1k_tokens", Decimal("0.002000")),
    "image_generation": ("image", Decimal("0.040000")),
    "image_edit": ("image", Decimal("0.040000")),
    "image_to_video": ("second", Decimal("0.080000")),
    "text_to_video": ("second", Decimal("0.080000")),
    "speech_generation": ("1k_characters", Decimal("0.015000")),
}


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def calculate_total_cost(quantity: Decimal, unit_cost: Decimal) -> Decimal:
    return _money(quantity * unit_cost)


def estimate_batch_cost(
    generation_count: int,
    average_units: Decimal,
    unit_cost: Decimal,
    uncertainty_ratio: Decimal = Decimal("0.15"),
) -> dict[str, Decimal]:
    base = calculate_total_cost(Decimal(generation_count) * average_units, unit_cost)
    uncertainty = (base * uncertainty_ratio).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return {
        "estimated": base,
        "minimum": max(Decimal("0"), base - uncertainty),
        "maximum": base + uncertainty,
    }


def operation_cost_policies(provider: str = "omniroute") -> list[OperationCostPolicyRead]:
    return [
        OperationCostPolicyRead(
            provider=provider,
            operation=operation,
            unit=unit,
            unit_cost=unit_cost,
        )
        for operation, (unit, unit_cost) in sorted(DEFAULT_OPERATION_COSTS_USD.items())
    ]


def estimate_operation_cost(
    operation: str,
    quantity: Decimal,
    provider: str = "omniroute",
    model: str | None = None,
    uncertainty_ratio: Decimal = Decimal("0.15"),
) -> OperationCostEstimateRead:
    normalized_operation = operation.strip().lower()
    if normalized_operation not in DEFAULT_OPERATION_COSTS_USD:
        allowed = ", ".join(sorted(DEFAULT_OPERATION_COSTS_USD))
        raise ValueError(f"Operacao de custo desconhecida: {operation}. Use: {allowed}")
    unit, unit_cost = DEFAULT_OPERATION_COSTS_USD[normalized_operation]
    estimate = estimate_batch_cost(1, quantity, unit_cost, uncertainty_ratio)
    return OperationCostEstimateRead(
        provider=provider,
        model=model,
        operation=normalized_operation,
        quantity=quantity,
        unit=unit,
        unit_cost=unit_cost,
        currency="USD",
        estimated=estimate["estimated"],
        minimum=estimate["minimum"],
        maximum=estimate["maximum"],
    )


async def create_cost_entry(session: AsyncSession, data: CostEntryCreate) -> CostEntry | None:
    project = await ProjectRepository(session).get_project(data.project_id)
    if project is None:
        return None
    if data.artifact_id is not None:
        artifact = await ProjectRepository(session).get_artifact(data.artifact_id)
        if artifact is None or artifact.project_id != data.project_id:
            return None

    entry = CostEntry(
        project_id=data.project_id,
        artifact_id=data.artifact_id,
        entry_type=data.entry_type,
        provider=data.provider,
        model=data.model,
        operation=data.operation,
        quantity=data.quantity,
        unit=data.unit,
        unit_cost=data.unit_cost,
        total_cost=calculate_total_cost(data.quantity, data.unit_cost),
        currency=data.currency.upper(),
        metadata_json=data.metadata_json,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


def _budget_decimal(value: object) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    if parsed < 0:
        return None
    return _money(parsed)


def _budget_map(value: object) -> dict[str, Decimal]:
    if not isinstance(value, dict):
        return {}
    budgets: dict[str, Decimal] = {}
    for key, raw_budget in value.items():
        budget = _budget_decimal(raw_budget)
        if budget is not None:
            budgets[str(key).strip().lower()] = budget
    return budgets


async def get_project_cost_budget(session: AsyncSession, project_id: UUID) -> CostBudgetRead:
    settings = await get_or_create_production_settings(session, project_id)
    metadata = settings.metadata_json or {}
    return CostBudgetRead(
        project_id=project_id,
        project_budget_usd=_budget_decimal(metadata.get("cost_budget_usd")),
        stage_budgets_usd=_budget_map(metadata.get("cost_stage_budgets_usd")),
    )


async def update_project_cost_budget(
    session: AsyncSession,
    project_id: UUID,
    payload: CostBudgetUpdate,
) -> CostBudgetRead | None:
    if await ProjectRepository(session).get_project(project_id) is None:
        return None
    settings = await get_or_create_production_settings(session, project_id)
    metadata = dict(settings.metadata_json or {})
    if payload.project_budget_usd is None:
        metadata.pop("cost_budget_usd", None)
    else:
        metadata["cost_budget_usd"] = str(_money(payload.project_budget_usd))
    metadata["cost_stage_budgets_usd"] = {
        key.strip().lower(): str(_money(value))
        for key, value in payload.stage_budgets_usd.items()
    }
    settings.metadata_json = metadata
    await session.commit()
    await session.refresh(settings)
    return await get_project_cost_budget(session, project_id)


def budget_allows(
    current_cost: Decimal,
    estimated_cost: Decimal,
    limit: Decimal | None,
) -> BudgetCheckRead:
    projected = _money(current_cost + estimated_cost)
    return BudgetCheckRead(
        allowed=limit is None or projected <= limit,
        current_cost=_money(current_cost),
        estimated_cost=_money(estimated_cost),
        projected_cost=projected,
        limit=limit,
    )


def _entry_stage(entry: CostEntry) -> str:
    metadata = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
    stage = metadata.get("stage") or entry.operation
    return str(stage or "uncategorized").strip().lower()


def _entry_total_for_budget(entry: CostEntry) -> Decimal:
    total = Decimal(entry.total_cost)
    if entry.entry_type == CostEntryType.CREDIT:
        return -total
    return total


async def project_cost_for_budget(
    session: AsyncSession,
    project_id: UUID,
    stage: str | None = None,
) -> Decimal:
    result = await session.execute(select(CostEntry).where(CostEntry.project_id == project_id))
    entries = list(result.scalars())
    normalized_stage = stage.strip().lower() if stage else None
    total = Decimal("0.000000")
    for entry in entries:
        if normalized_stage is not None and _entry_stage(entry) != normalized_stage:
            continue
        total += _entry_total_for_budget(entry)
    return _money(total)


async def check_project_budget(
    session: AsyncSession,
    project_id: UUID,
    estimated_cost: Decimal,
    stage: str | None = None,
) -> BudgetCheckRead:
    budget = await get_project_cost_budget(session, project_id)
    normalized_stage = stage.strip().lower() if stage else None
    stage_limit = (
        budget.stage_budgets_usd.get(normalized_stage)
        if normalized_stage is not None
        else None
    )
    limit = stage_limit if stage_limit is not None else budget.project_budget_usd
    current = await project_cost_for_budget(
        session,
        project_id,
        normalized_stage if stage_limit is not None else None,
    )
    check = budget_allows(current, estimated_cost, limit)
    check.stage = normalized_stage
    return check


async def assert_project_budget_allows(
    session: AsyncSession,
    project_id: UUID,
    estimated_cost: Decimal,
    stage: str | None = None,
) -> None:
    check = await check_project_budget(session, project_id, estimated_cost, stage)
    if not check.allowed:
        raise CostBudgetExceededError(check)


def _empty_breakdown(key: str) -> CostBreakdownItemRead:
    return CostBreakdownItemRead(key=key)


def _add_to_breakdown(item: CostBreakdownItemRead, entry: CostEntry) -> None:
    total = Decimal(entry.total_cost)
    if entry.entry_type == CostEntryType.ESTIMATE:
        item.estimated_cost = _money(item.estimated_cost + total)
    elif entry.entry_type == CostEntryType.ACTUAL:
        item.actual_cost = _money(item.actual_cost + total)
    else:
        item.credit = _money(item.credit + total)
    item.total_cost = _money(item.estimated_cost + item.actual_cost - item.credit)


def _sorted_breakdown(items: dict[str, CostBreakdownItemRead]) -> list[CostBreakdownItemRead]:
    return sorted(items.values(), key=lambda item: item.key)


async def project_cost_summary(
    session: AsyncSession,
    project_id: UUID,
) -> ProjectCostSummaryRead:
    result = await session.execute(select(CostEntry).where(CostEntry.project_id == project_id))
    entries = list(result.scalars())
    by_stage: dict[str, CostBreakdownItemRead] = {}
    by_provider: dict[str, CostBreakdownItemRead] = {}
    by_model: dict[str, CostBreakdownItemRead] = {}
    estimated = Decimal("0.000000")
    actual = Decimal("0.000000")
    credit = Decimal("0.000000")
    for entry in entries:
        if entry.entry_type == CostEntryType.ESTIMATE:
            estimated += Decimal(entry.total_cost)
        elif entry.entry_type == CostEntryType.ACTUAL:
            actual += Decimal(entry.total_cost)
        else:
            credit += Decimal(entry.total_cost)

        stage = _entry_stage(entry)
        provider = entry.provider or "unknown"
        model = entry.model or "unknown"
        _add_to_breakdown(by_stage.setdefault(stage, _empty_breakdown(stage)), entry)
        _add_to_breakdown(by_provider.setdefault(provider, _empty_breakdown(provider)), entry)
        _add_to_breakdown(by_model.setdefault(model, _empty_breakdown(model)), entry)

    return ProjectCostSummaryRead(
        project_id=project_id,
        estimated_cost=_money(estimated),
        actual_cost=_money(actual),
        credit=_money(credit),
        total_cost=_money(estimated + actual - credit),
        estimated_vs_actual_delta=_money(actual - estimated),
        by_stage=_sorted_breakdown(by_stage),
        by_provider=_sorted_breakdown(by_provider),
        by_model=_sorted_breakdown(by_model),
    )
