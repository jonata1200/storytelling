from decimal import Decimal

from app.costs.service import (
    budget_allows,
    calculate_total_cost,
    estimate_batch_cost,
    estimate_operation_cost,
)


def test_calculate_total_cost_quantizes_to_six_decimal_places() -> None:
    assert calculate_total_cost(Decimal("3"), Decimal("0.3333333")) == Decimal("1.000000")


def test_estimate_batch_cost_returns_uncertainty_range() -> None:
    estimate = estimate_batch_cost(
        generation_count=10,
        average_units=Decimal("2"),
        unit_cost=Decimal("0.50"),
        uncertainty_ratio=Decimal("0.10"),
    )

    assert estimate["estimated"] == Decimal("10.000000")
    assert estimate["minimum"] == Decimal("9.000000")
    assert estimate["maximum"] == Decimal("11.000000")


def test_estimate_operation_cost_uses_default_policy() -> None:
    estimate = estimate_operation_cost("image_to_video", Decimal("12.5"), model="video/model")

    assert estimate.unit == "second"
    assert estimate.unit_cost == Decimal("0.080000")
    assert estimate.estimated == Decimal("1.000000")
    assert estimate.maximum == Decimal("1.150000")


def test_budget_allows_blocks_when_projected_cost_exceeds_limit() -> None:
    check = budget_allows(
        current_cost=Decimal("9.50"),
        estimated_cost=Decimal("1.00"),
        limit=Decimal("10.00"),
    )

    assert check.allowed is False
    assert check.projected_cost == Decimal("10.500000")
