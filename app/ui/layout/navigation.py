from nicegui import ui

from app.config.preferences import save_preferences
from app.config.settings import get_settings
from app.projects.models import Project
from app.ui.shared.page_config import BRAND_MARK_URL, WORKSPACE_TABS
from app.ui.workspace.rules import workspace_section_access

HOME_NAV_ITEMS = [
    ("ideas", "lightbulb_outline", "Ideias", "/"),
    ("create", "chat_bubble_outline", "Criar", "/dashboard"),
    ("projects", "folder_open", "Projetos", "/projects"),
    ("settings", "settings", "Ajustes", "/settings"),
]

WORKSPACE_NAV_ICONS = {
    "script": "description",
    "visual": "palette",
    "storyboard": "view_comfy",
    "video": "movie",
    "finalization": "check_circle",
}


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


def home_sidebar(active: str = "") -> None:
    with ui.column().classes(
        "desktop-nav fixed left-0 top-0 bottom-0 w-24 border-r border-[#222622] "
        "items-center py-6 gap-6 bg-[#0b0d0c] z-20"
    ):
        studio_logo(compact=True)
        for key, icon, label, target in HOME_NAV_ITEMS:
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
    with ui.element("nav").classes("mobile-bottom-nav mobile-home-nav"):
        for key, icon, label, target in HOME_NAV_ITEMS:
            item_classes = "mobile-nav-item"
            if key == active:
                item_classes += " mobile-nav-active"
            with (
                ui.element("button")
                .classes(item_classes)
                .props("type=button")
                .on("click", lambda t=target: ui.navigate.to(t))
            ):
                ui.icon(icon).classes("mobile-nav-icon")
                ui.label(label).classes("mobile-nav-label")


def workspace_header(
    project: Project,
    active: str,
    counts: dict[str, int],
    workflow_mode: object = None,
) -> None:
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
                allowed, reason = workspace_section_access(key, counts, workflow_mode)
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
        with ui.row().classes("workspace-theme-action items-center justify-end"):
            theme_toggle()
    with ui.element("nav").classes("mobile-bottom-nav mobile-workspace-nav"):
        for label, key in WORKSPACE_TABS:
            allowed, reason = workspace_section_access(key, counts, workflow_mode)
            item_classes = "mobile-nav-item"
            if active == key:
                item_classes += " mobile-nav-active"
            if not allowed:
                item_classes += " mobile-nav-disabled"
            with (
                ui.element("button")
                .classes(item_classes)
                .props("type=button" if allowed else "type=button disabled")
                .on("click", lambda k=key: ui.navigate.to(f"/projects/{project.id}/{k}"))
            ) as nav_button:
                ui.icon(WORKSPACE_NAV_ICONS.get(key, "radio_button_unchecked")).classes(
                    "mobile-nav-icon"
                )
                ui.label(label).classes("mobile-nav-label")
            if not allowed:
                nav_button.tooltip(reason)


