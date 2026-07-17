from app.production.service import WORKFLOW_MODES, workflow_mode_label


def test_workflow_mode_label_uses_known_name() -> None:
    assert workflow_mode_label("keyframes_i2v") == WORKFLOW_MODES["keyframes_i2v"]


def test_workflow_mode_label_falls_back_to_raw_value() -> None:
    assert workflow_mode_label("custom") == "custom"
