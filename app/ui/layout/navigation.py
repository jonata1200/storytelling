from pathlib import Path
from typing import Any

from nicegui import ui

from app.config.preferences import save_preferences
from app.config.settings import get_settings
from app.projects.models import Project
from app.providers.media_utils import local_uri_to_data_url
from app.ui.shared.page_config import BRAND_MARK_URL, WORKSPACE_TABS
from app.ui.workspace.rules import workspace_section_access


def studio_logo(compact: bool = False) -> None:
    with ui.row().classes("items-center gap-3"):
        ui.image(BRAND_MARK_URL).classes("w-9 h-9 rounded-xl object-cover")
        if not compact:
            ui.label("Storytelling").classes("brand-type text-xl font-extrabold")


def theme_toggle() -> None:
    is_dark = get_settings().user_theme != "light"
    mode = ui.dark_mode(value=is_dark)
    button = ui.button(icon="light_mode" if is_dark else "dark_mode").props("flat round")

    def toggle_theme() -> None:
        next_dark = not bool(mode.value)
        mode.set_value(next_dark)
        save_preferences({"USER_THEME": "dark" if next_dark else "light"})
        button.props(f"icon={'light_mode' if next_dark else 'dark_mode'}")
        button.update()

    button.on("click", toggle_theme).tooltip("Alternar entre tema claro e escuro")


def avatar_data_uri(path_value: str) -> str | None:
    if not path_value:
        return None
    data_uri = local_uri_to_data_url(path_value)
    return data_uri if data_uri.startswith("data:") else None


def save_avatar_file(filename: str, content: bytes) -> Path:
    suffix = Path(filename).suffix.lower()
    target_dir = get_settings().local_storage_path / "profile"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"avatar{suffix}"
    target.write_bytes(content)
    return target


def user_avatar(size: str = "44px", navigate: bool = True) -> Any:
    current = get_settings()
    image_source = avatar_data_uri(current.user_avatar_path)
    initial = (current.user_display_name or "U").strip()[:1].upper()
    with ui.avatar(color="grey-9", size=size).classes(
        "cursor-pointer overflow-hidden ring-1 ring-[#3a3f3a]"
    ) as avatar:
        if image_source:
            ui.image(image_source).classes("w-full h-full object-cover").props("fit=cover")
        else:
            ui.label(initial)
    if navigate:
        avatar.on("click", lambda: ui.navigate.to("/settings"))
    return avatar


def home_sidebar(active: str = "") -> None:
    with ui.column().classes(
        "desktop-nav fixed left-0 top-0 bottom-0 w-24 border-r border-[#222622] "
        "items-center py-6 gap-6 bg-[#0b0d0c] z-20"
    ):
        studio_logo(compact=True)
        for key, icon, label, target in [
            ("ideas", "lightbulb_outline", "Ideias", "/"),
            ("create", "chat_bubble_outline", "Criar", "/dashboard"),
            ("projects", "folder_open", "Projetos", "/projects"),
            ("settings", "settings", "Ajustes", "/settings"),
        ]:
            active_classes = "acid" if key == active else "text-[#8d928e]"
            with (
                ui.column()
                .classes(
                    "items-center gap-1 cursor-pointer rounded-xl px-3 py-2 "
                    f"{active_classes} hover:text-white"
                )
                .on("click", lambda t=target: ui.navigate.to(t))
            ):
                ui.icon(icon).classes("text-2xl")
                ui.label(label).classes("text-[11px]")
        ui.space()
        with ui.element("div").classes("mb-2"):
            user_avatar(size="48px")


def workspace_header(project: Project, active: str, counts: dict[str, int]) -> None:
    with ui.element("header").classes(
        "workspace-header sticky top-0 z-30 w-full border-b border-[#242824] bg-[#090b0a]"
    ):
        with ui.row().classes("workspace-titlebar items-center gap-3"):
            studio_logo(compact=True)
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props(
                "flat round dense"
            ).classes("text-[#9da29d] shrink-0")
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(project.title).classes("font-semibold truncate max-w-72")
                ui.label("Episodio 1").classes(
                    "workspace-episode text-[11px] text-[#818681]"
                )
            if counts.get("stale_artifacts", 0):
                ui.badge(f"{counts['stale_artifacts']} desatualizado(s)").classes(
                    "bg-amber-900 text-amber-100 shrink-0"
                ).tooltip("Alguns artefatos derivados precisam ser regenerados.")
        with ui.row().classes("workspace-nav desktop-nav items-center gap-1"):
            for label, key in WORKSPACE_TABS:
                allowed, reason = workspace_section_access(key, counts)
                button = ui.button(
                    label,
                    icon=None if allowed else "lock",
                    on_click=lambda k=key: ui.navigate.to(f"/projects/{project.id}/{k}"),
                ).props("flat no-caps" if allowed else "flat no-caps disable").classes(
                    f"nav-pill rounded-full px-3 {'nav-active' if active == key else ''} "
                    f"{'nav-locked cursor-not-allowed' if not allowed else ''}"
                )
                if not allowed:
                    button.tooltip(reason)
        with ui.row().classes("workspace-actions items-center gap-3"):
            ui.label("PT-BR").classes("desktop-nav text-sm text-[#a9aea9] shrink-0")
            theme_toggle()
            ui.button("Exportar", icon="ios_share").props("unelevated no-caps").classes(
                "acid-bg workspace-export-button rounded-xl font-semibold shrink-0"
            )


