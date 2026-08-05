from collections.abc import Callable
from typing import Any

from nicegui import ui

from app.ui.shared.page_config import BLOCKING_DIALOG_PROPS


def progress_ratio(done: int, total: int) -> float:
    return min(max(done / total, 0.0), 1.0) if total else 0.0


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
            progress_label = ui.label(f"0/{total} {item_label}(s) processado(s)")
            progress_label.classes("text-sm text-[#d8dbd8]")
            progress_bar = ui.linear_progress(value=0).classes("w-full")
            progress_bar.props("instant-feedback rounded")
            progress_detail = ui.label(initial_detail).classes(
                "text-xs text-[#8d938e] text-center"
            )

    def update_progress(completed: int, current_total: int, detail: str) -> None:
        safe_total = max(current_total, 1)
        progress_label.set_text(
            f"{completed}/{current_total} {item_label}(s) processado(s)"
        )
        progress_bar.set_value(progress_ratio(completed, safe_total))
        progress_detail.set_text(detail)

    return progress_dialog, update_progress
