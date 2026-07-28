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
        {"image_model": " sourceful/riverflow-v2.5-pro ", "motion_intensity": "7"}
    )

    assert payload["image_model"] == "sourceful/riverflow-v2.5-pro"
    assert payload["motion_intensity"] == 7


def test_production_payload_rejects_mock_and_openrouter_free_models() -> None:
    with pytest.raises(ValueError, match="mock"):
        _validated_production_payload({"image_model": "mock-image"})

    with pytest.raises(ValueError, match="free"):
        _validated_production_payload({"video_model": "google/gemini-flash-1.5:free"})


def test_resolve_image_model_uses_global_default_when_project_is_mock() -> None:
    assert (
        resolve_image_model("mock-image", "krea/krea-2-medium-turbo")
        == "krea/krea-2-medium-turbo"
    )


def test_resolve_image_model_preserves_project_specific_real_model() -> None:
    assert (
        resolve_image_model("krea/krea-2-medium-turbo", "sourceful/riverflow-v2-fast")
        == "krea/krea-2-medium-turbo"
    )


def test_resolve_image_model_uses_global_default_for_legacy_project_default() -> None:
    assert (
        resolve_image_model("sourceful/riverflow-v2.5-pro", "sourceful/riverflow-v2-fast")
        == "sourceful/riverflow-v2-fast"
    )


def test_resolve_image_model_requires_real_model_when_no_default_exists() -> None:
    with pytest.raises(ValueError, match="modelo real"):
        resolve_image_model("mock-image", "")
