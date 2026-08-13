import pytest

from app.production.service import (
    WORKFLOW_MODES,
    _validated_production_payload,
    resolve_image_model,
    workflow_mode_label,
)


def test_workflow_mode_label_uses_known_name() -> None:
    assert workflow_mode_label("continuous_fast") == WORKFLOW_MODES["continuous_fast"]
    assert workflow_mode_label("keyframes_i2v") == "keyframes_i2v"  # legado: sem rotulo ativo


def test_workflow_mode_label_falls_back_to_raw_value() -> None:
    assert workflow_mode_label("custom") == "custom"


def test_production_payload_rejects_invalid_domain_values() -> None:
    with pytest.raises(ValueError, match="motion_intensity"):
        _validated_production_payload({"motion_intensity": 11})


def test_production_payload_normalizes_model_and_intensity() -> None:
    payload = _validated_production_payload(
        {"image_model": " gemini-3.1-flash-lite-image ", "motion_intensity": "7"}
    )

    assert payload["image_model"] == "gemini-3.1-flash-lite-image"
    assert payload["motion_intensity"] == 7


def test_production_payload_normalizes_video_resolution_to_720p() -> None:
    payload = _validated_production_payload({"video_resolution": "1080x1920"})

    assert payload["video_resolution"] == "720p"


def test_production_payload_accepts_continuous_video_mode() -> None:
    payload = _validated_production_payload({"workflow_mode": "continuous_fast"})

    assert payload["workflow_mode"] == "continuous_fast"


def test_production_payload_normalizes_image_aspect_and_resolution() -> None:
    vertical = _validated_production_payload(
        {"aspect_ratio": "1:1", "image_resolution": "3840x2160"}
    )
    horizontal = _validated_production_payload(
        {"aspect_ratio": "16:9", "image_resolution": "1920x1080"}
    )

    assert vertical["aspect_ratio"] == "9:16"
    assert vertical["image_resolution"] == "720x1280"
    assert horizontal["aspect_ratio"] == "16:9"
    assert horizontal["image_resolution"] == "1280x720"


def test_production_payload_rejects_mock_and_free_models() -> None:
    with pytest.raises(ValueError, match="mock"):
        _validated_production_payload({"image_model": "mock-image"})

    with pytest.raises(ValueError, match="free"):
        _validated_production_payload({"video_model": "google/gemini-flash-1.5:free"})

    with pytest.raises(ValueError, match="Modelo inválido"):
        _validated_production_payload({"image_model": "gemini-3.1-flash-image"})


def test_resolve_image_model_uses_global_default_when_project_is_mock() -> None:
    assert (
        resolve_image_model("mock-image", "gemini-3.1-flash-lite-image")
        == "gemini-3.1-flash-lite-image"
    )


def test_resolve_image_model_preserves_project_specific_allowed_model() -> None:
    assert (
        resolve_image_model("gemini-3.1-flash-lite-image", "gemini-3.1-flash-image")
        == "gemini-3.1-flash-lite-image"
    )


def test_resolve_image_model_uses_global_default_for_legacy_project_default() -> None:
    assert (
        resolve_image_model("sourceful/riverflow-v2-fast", "gemini-3.1-flash-image")
        == "gemini-3.1-flash-lite-image"
    )


def test_resolve_image_model_requires_real_model_when_no_default_exists() -> None:
    with pytest.raises(ValueError, match="modelo real"):
        resolve_image_model("mock-image", "")

