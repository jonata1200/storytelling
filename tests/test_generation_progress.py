import pytest

from app.ui.shared import page_config
from app.ui.shared.generation_progress import progress_percent_text, progress_ratio
from app.ui.shared.page_config import (
    is_deleted_ui_context_error,
    play_completion_sound,
    safe_close_ui_element,
    safe_notify,
)
from app.ui.visual.actions import _emit_visual_batch_progress


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


def test_deleted_ui_context_errors_are_detected() -> None:
    assert is_deleted_ui_context_error(
        RuntimeError("The client this element belongs to has been deleted.")
    )
    assert is_deleted_ui_context_error(
        RuntimeError("The parent element this slot belongs to has been deleted.")
    )
    assert not is_deleted_ui_context_error(RuntimeError("other failure"))


def test_safe_close_ui_element_ignores_deleted_client() -> None:
    class DeletedDialog:
        def close(self) -> None:
            raise RuntimeError("The client this element belongs to has been deleted.")

    safe_close_ui_element(DeletedDialog())


def test_safe_notify_ignores_deleted_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    def deleted_notify(_message: str, **_kwargs: object) -> None:
        raise RuntimeError("The parent element this slot belongs to has been deleted.")

    monkeypatch.setattr(page_config.ui, "notify", deleted_notify)

    safe_notify("Ideia apagada definitivamente.", color="warning")


def test_play_completion_sound_runs_browser_audio_script(monkeypatch: pytest.MonkeyPatch) -> None:
    scripts: list[str] = []
    monkeypatch.setattr(page_config.core, "loop", object())
    monkeypatch.setattr(page_config.ui, "run_javascript", scripts.append)

    play_completion_sound()

    assert scripts
    assert "AudioContext" in scripts[0]
    assert "storytellingCompletionSound" in scripts[0]


def test_play_completion_sound_ignores_deleted_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def deleted_context(_script: str) -> None:
        raise RuntimeError("The client this element belongs to has been deleted.")

    monkeypatch.setattr(page_config.core, "loop", object())
    monkeypatch.setattr(page_config.ui, "run_javascript", deleted_context)

    play_completion_sound()


async def test_visual_progress_ignores_deleted_client() -> None:
    def callback(_completed: int, _total: int, _detail: str) -> None:
        raise RuntimeError("The client this element belongs to has been deleted.")

    await _emit_visual_batch_progress(callback, 1, 2, "Gerando")
