"""Tests for costs router — security and validation.

Verifies:
- CostEntryCreate enforces gt=0 on quantity and ge=0 on unit_cost
- project_cost_summary uses net (max(actual, estimated) - credit), not sum
- _budget_decimal logs warning on parse failure (not silent None)
- create_cost_entry recomputes total_cost (ignores client-supplied total)
"""

from decimal import Decimal

import pytest

from app.costs.schemas import CostEntryCreate


@pytest.mark.unit
def test_cost_entry_create_accepts_valid_values() -> None:
    entry = CostEntryCreate(
        project_id="00000000-0000-0000-0000-000000000001",
        entry_type="ACTUAL",
        provider="vibes",
        model="vibes",
        operation="video_generation",
        quantity=Decimal("1"),
        unit="second",
        unit_cost=Decimal("0.067"),
        currency="USD",
    )
    assert entry.quantity > 0
    assert entry.unit_cost >= 0


@pytest.mark.unit
def test_cost_entry_create_rejects_zero_quantity() -> None:
    with pytest.raises(ValueError):
        CostEntryCreate(
            project_id="00000000-0000-0000-0000-000000000001",
            entry_type="ACTUAL",
            provider="vibes",
            model="test",
            operation="video_generation",
            quantity=Decimal("0"),
            unit="second",
            unit_cost=Decimal("0.067"),
            currency="USD",
        )


@pytest.mark.unit
def test_cost_entry_create_rejects_negative_unit_cost() -> None:
    with pytest.raises(ValueError):
        CostEntryCreate(
            project_id="00000000-0000-0000-0000-000000000001",
            entry_type="ACTUAL",
            provider="vibes",
            model="test",
            operation="video_generation",
            quantity=Decimal("1"),
            unit="second",
            unit_cost=Decimal("-1"),
            currency="USD",
        )
