from decimal import Decimal

from app.costs.service import calculate_total_cost, estimate_batch_cost


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
