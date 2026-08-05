from app.ui.shared.generation_progress import progress_percent_text, progress_ratio


def test_progress_ratio_is_clamped() -> None:
    assert progress_ratio(0, 0) == 0.0
    assert progress_ratio(-1, 10) == 0.0
    assert progress_ratio(5, 10) == 0.5
    assert progress_ratio(12, 10) == 1.0


def test_progress_percent_text_uses_percentage() -> None:
    assert progress_percent_text(0, 10) == "0%"
    assert progress_percent_text(1, 4) == "25%"
    assert progress_percent_text(2, 3) == "67%"
    assert progress_percent_text(10, 10) == "100%"
