from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.costs.schemas import BudgetCheckRead
from app.costs.service import (
    assert_project_budget_allows,
    budget_allows,
    calculate_total_cost,
    cost_audit_metadata,
    estimate_batch_cost,
    estimate_operation_cost,
    final_budget_cost,
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
    assert estimate.unit_cost == Decimal("0.400000")
    assert estimate.estimated == Decimal("5.000000")
    assert estimate.maximum == Decimal("5.750000")


def test_budget_allows_blocks_when_projected_cost_exceeds_limit() -> None:
    check = budget_allows(
        current_cost=Decimal("9.50"),
        estimated_cost=Decimal("1.00"),
        limit=Decimal("10.00"),
    )

    assert check.allowed is False
    assert check.projected_cost == Decimal("10.500000")


def test_cost_audit_metadata_separates_estimated_provider_and_budget_cost() -> None:
    metadata = cost_audit_metadata(
        estimated_cost=Decimal("0.040000"),
        provider_reported_cost=Decimal("0.052000"),
        final_budget_cost=final_budget_cost(Decimal("0.040000"), Decimal("0.052000")),
        stage="storyboard",
        extra={"asset_id": "asset-1"},
    )

    assert metadata["estimated_cost"] == "0.040000"
    assert metadata["provider_reported_cost"] == "0.052000"
    assert metadata["final_budget_cost"] == "0.052000"
    assert metadata["stage"] == "storyboard"
    assert metadata["asset_id"] == "asset-1"


def test_mock_provider_cost_policy_is_zero() -> None:
    estimate = estimate_operation_cost("image_generation", Decimal("3"), provider="mock")

    assert estimate.unit_cost == Decimal("0.000000")
    assert estimate.estimated == Decimal("0.000000")


def test_google_ai_cost_policy_uses_model_overrides() -> None:
    image = estimate_operation_cost(
        "image_generation",
        Decimal("1"),
        provider="google_ai",
        model="gemini-3.1-flash-lite-image",
    )
    video = estimate_operation_cost(
        "image_to_video",
        Decimal("8"),
        provider="google_ai",
        model="veo-3.1-fast-generate-preview",
    )

    assert image.unit == "image"
    assert image.unit_cost == Decimal("0.033600")
    assert video.unit == "second"
    assert video.estimated == Decimal("0.800000")


def test_elevenlabs_cost_policy_uses_speech_and_dubbing_units() -> None:
    speech = estimate_operation_cost(
        "speech_generation",
        Decimal("2"),
        provider="elevenlabs",
        model="eleven_flash_v2_5",
    )
    dubbing = estimate_operation_cost(
        "dubbing",
        Decimal("3"),
        provider="elevenlabs",
        model="dubbing-v1",
    )

    assert speech.unit == "1k_characters"
    assert speech.estimated == Decimal("0.100000")
    assert dubbing.unit == "minute"
    assert dubbing.estimated == Decimal("0.990000")


class _FakeBudgetSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)


@pytest.mark.asyncio
async def test_assert_project_budget_allows_emits_event_when_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    session = _FakeBudgetSession()

    async def blocked_check(
        _session: AsyncSession,
        _project_id: Any,
        estimated_cost: Decimal,
        stage: str | None = None,
    ) -> BudgetCheckRead:
        return BudgetCheckRead(
            allowed=False,
            current_cost=Decimal("9.000000"),
            estimated_cost=estimated_cost,
            projected_cost=Decimal("11.000000"),
            limit=Decimal("10.000000"),
            stage=stage,
        )

    monkeypatch.setattr("app.costs.service.check_project_budget", blocked_check)

    with pytest.raises(ValueError, match="excede"):
        await assert_project_budget_allows(
            cast(AsyncSession, session),
            project_id,
            Decimal("2.000000"),
            stage="video",
        )

    event = session.added[0]
    assert event.event_type == "budget"
    assert event.status == "blocked"
    assert event.operation == "video"
