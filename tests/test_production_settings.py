import pytest

from app.production.service import (
    WORKFLOW_MODES,
    _validated_production_payload,
    workflow_mode_label,
)


def test_workflow_mode_label_uses_known_name() -> None:
    assert workflow_mode_label("keyframes_i2v") == WORKFLOW_MODES["keyframes_i2v"]


def test_workflow_mode_label_falls_back_to_raw_value() -> None:
    assert workflow_mode_label("custom") == "custom"


def test_production_payload_rejects_invalid_domain_values() -> None:
    with pytest.raises(ValueError, match="aspect_ratio"):
        _validated_production_payload({"aspect_ratio": "21:9"})

    with pytest.raises(ValueError, match="motion_intensity"):
        _validated_production_payload({"motion_intensity": 11})


def test_production_payload_normalizes_model_and_intensity() -> None:
    payload = _validated_production_payload(
        {"image_model": " mock-image ", "motion_intensity": "7"}
    )

    assert payload["image_model"] == "mock-image"
    assert payload["motion_intensity"] == 7
