from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.costs.models import CostEntry
from app.costs.schemas import CostEntryCreate
from app.projects.repository import ProjectRepository


def calculate_total_cost(quantity: Decimal, unit_cost: Decimal) -> Decimal:
    return (quantity * unit_cost).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


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


async def create_cost_entry(session: AsyncSession, data: CostEntryCreate) -> CostEntry | None:
    project = await ProjectRepository(session).get_project(data.project_id)
    if project is None:
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
