import logging
from collections.abc import Callable
from typing import Any

from nicegui import ui

from app.ui.shared.page_config import BLOCKING_DIALOG_PROPS, is_deleted_ui_context_error

logger = logging.getLogger(__name__)


def progress_ratio(done: int, total: int) -> float:
    return min(max(done / total, 0.0), 1.0) if total else 0.0


def progress_percent_text(done: int, total: int) -> str:
    return f"{round(progress_ratio(done, total) * 100)}%"


def generation_progress_dialog(
    title: str,
    total: int,
    item_label: str,
    initial_detail: str,
) -> tuple[Any, Callable[[int, int, str], None]]:
    with ui.dialog().props(BLOCKING_DIALOG_PROPS) as progress_dialog, ui.card().classes(
        "entity-card rounded-2xl p-6 w-[min(520px,92vw)]"
    ):
        with ui.column().classes("w-full items-center gap-4"):
            ui.spinner(size="lg").classes("acid")
            ui.label(title).classes("brand-type text-2xl font-bold")
            progress_label = ui.label(
                f"0/{total} {item_label}(s) processado(s) - {progress_percent_text(0, total)}"
            )
            progress_label.classes("text-sm text-[#d8dbd8]")
            progress_bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
            progress_bar.props("instant-feedback rounded")
            progress_detail = ui.label(initial_detail).classes(
                "text-xs text-[#8d938e] text-center whitespace-pre-line"
            )

    def update_progress(completed: int, current_total: int, detail: str) -> None:
        safe_total = max(current_total, 1)
        try:
            progress_label.set_text(
                f"{completed}/{current_total} {item_label}(s) processado(s) - "
                f"{progress_percent_text(completed, current_total)}"
            )
            progress_bar.set_value(progress_ratio(completed, safe_total))
            progress_detail.set_text(detail)
        except RuntimeError as exc:
            if not is_deleted_ui_context_error(exc):
                raise
            logger.warning("Generation progress ignored because the page context was removed.")

    return progress_dialog, update_progress
