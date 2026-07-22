import pytest

from app.production.service import (
    WORKFLOW_MODES,
    _validated_production_payload,
    resolve_image_model,
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


def test_resolve_image_model_uses_global_default_when_project_is_mock() -> None:
    assert (
        resolve_image_model("mock-image", "krea/krea-2-medium-turbo")
        == "krea/krea-2-medium-turbo"
    )


def test_resolve_image_model_preserves_project_specific_real_model() -> None:
    assert (
        resolve_image_model("google/gemini-2.5-flash-image", "krea/krea-2-medium-turbo")
        == "google/gemini-2.5-flash-image"
    )


def test_resolve_image_model_falls_back_to_mock_when_no_default_exists() -> None:
    assert resolve_image_model("mock-image", "") == "mock-image"
