import pytest

from app.production.service import (
    WORKFLOW_MODES,
    _validated_production_payload,
    workflow_mode_label,
)


def test_workflow_mode_label_uses_known_name() -> None:
    assert workflow_mode_label("continuous_fast") == WORKFLOW_MODES["continuous_fast"]


def test_production_payload_rejects_invalid_motion() -> None:
    with pytest.raises(ValueError, match="motion_intensity"):
        _validated_production_payload({"motion_intensity": 11})


def test_production_payload_normalizes_video_dimensions() -> None:
    payload = _validated_production_payload(
        {"aspect_ratio": "16:9", "video_resolution": "720p"}
    )
    assert payload["aspect_ratio"] == "16:9"
    assert payload["video_resolution"] == "720p"


def test_production_payload_rejects_unsupported_video_resolution() -> None:
    with pytest.raises(ValueError, match="Resolução de vídeo não suportada"):
        _validated_production_payload({"video_resolution": "1080p"})
