"""Small rendering components shared by the continuous-video workspace."""

from typing import Any

from nicegui import ui

from app.ui.shared.generation_progress import progress_ratio


def render_generation_progress_summary(
    title: str,
    generated: int,
    total: int,
    missing: int,
    detail: str,
    *,
    badge: str | None = None,
) -> None:
    with ui.element("div").classes(
        "w-full border border-[#343934] rounded-xl px-4 py-3 bg-[#0d100e] mb-3"
    ):
        with ui.row().classes("w-full items-center justify-between gap-3"):
            with ui.column().classes("gap-0"):
                ui.label(f"{title}: {generated}/{total}").classes(
                    "text-sm font-semibold text-[#d8dbd8]"
                )
                ui.label(f"Faltam {missing}. {detail}").classes("text-xs text-[#8d938e]")
            ui.badge(badge or ("pronto" if missing == 0 and total else "pendente")).classes(
                "bg-[#26301f] text-white"
                if missing == 0 and total
                else "blue-status-badge bg-[#243342]"
            )
        ui.linear_progress(
            value=progress_ratio(generated, total),
            show_value=False,
        ).classes("w-full mt-3").props("instant-feedback rounded")


def render_continuity_checks(checks: list[dict[str, Any]]) -> None:
    if not checks:
        return
    with ui.row().classes("w-full flex-wrap gap-2 mt-2"):
        for check in checks:
            ok = bool(check.get("ok"))
            label = str(check.get("label") or "")
            detail = str(check.get("detail") or "").strip()
            text = f"{label}: {detail}" if detail else label
            with ui.element("div").classes(
                (
                    "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs "
                    "bg-[#26301f] text-[#eaf878]"
                )
                if ok
                else (
                    "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs "
                    "bg-[#4b2a2a] text-[#ffd4d4]"
                )
            ):
                ui.icon("check_circle" if ok else "error_outline").classes("text-sm")
                ui.label(text)
