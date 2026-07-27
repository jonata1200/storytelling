import sys
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nicegui import ui

from app.ui.project.assistant_panel import render_assistant_panel
from app.ui.routes.home_pages import register_home_pages
from app.ui.routes.project_workspace_page import register_project_workspace_pages
from app.ui.routes.settings_page import register_settings_page
from app.ui.shared import assistant_state
from app.ui.visual.helpers import asset_url as _visual_asset_url
from app.ui.workspace.assets_area import render_assets_area
from app.ui.workspace.script_area import render_script_area, save_script_from_ui
from app.ui.workspace.storyboard_video_area import render_storyboard_area, render_video_area


def _page_attr(name: str) -> Any:
    pages = sys.modules["app.ui.pages"]
    return getattr(pages, name)


def _notify_ai_action_failure_once(project_id: UUID, summary: dict[str, Any]) -> None:
    nicegui_app = _page_attr("nicegui_app")
    ai_action = _project_ai_action(summary)
    if str(ai_action.get("status") or "") != "failed":
        return
    action = str(ai_action.get("action") or "ai_action")
    updated_at = str(ai_action.get("updated_at") or "")
    error = str(ai_action.get("error") or ai_action.get("message") or "").strip()
    notification_key = f"{project_id}:{action}:{updated_at}:{error}"
    store = nicegui_app.storage.user.setdefault("seen_ai_error_notifications", [])
    seen = [str(item) for item in store if isinstance(item, str)]
    if notification_key in seen:
        return
    seen.append(notification_key)
    nicegui_app.storage.user["seen_ai_error_notifications"] = seen[-80:]
    _page_attr("_show_ai_error_popup")(
        error or "A IA não respondeu. Tente novamente ou escolha outro modelo.",
        details=error,
    )


def _sync_ai_action_events_to_chat(project_id: UUID, summary_or_action: dict[str, Any]) -> None:
    nicegui_app = _page_attr("nicegui_app")
    assistant_state.nicegui_app = nicegui_app
    ai_action = (
        _project_ai_action(summary_or_action)
        if "production_settings" in summary_or_action
        else summary_or_action
    )
    assistant_state.sync_ai_action_events_to_chat(project_id, ai_action)


def _assistant_panel(project_id: UUID, active: str, summary: dict[str, Any]) -> None:
    render_assistant_panel(
        project_id,
        active,
        summary,
        loading_dialog_factory=_page_attr("_generation_loading_dialog"),
        project_ai_action=_project_ai_action,
        sync_ai_action_events_to_chat=_sync_ai_action_events_to_chat,
        notify_ai_action_failure_once=_notify_ai_action_failure_once,
    )


def _section_title(title: str, subtitle: str, action: str | None, callback: Any | None) -> None:
    with ui.row().classes("w-full items-end justify-between mb-2"):
        with ui.column().classes("gap-1"):
            ui.label(title).classes("brand-type text-3xl font-bold")
            ui.label(subtitle).classes("text-sm text-[#8e948f]")
        if action and callback:
            ui.button(action, icon="auto_awesome", on_click=callback).props(
                "unelevated no-caps"
            ).classes("acid-bg rounded-xl font-semibold")


def _project_ai_action(summary: dict[str, Any]) -> dict[str, Any]:
    settings = summary.get("production_settings")
    metadata = getattr(settings, "metadata_json", {}) or {}
    action = metadata.get("ai_action")
    return action if isinstance(action, dict) else {}


def _ai_action_is_stale(action: dict[str, Any], max_age_seconds: int = 120) -> bool:
    status = str(action.get("status") or "")
    if status not in {"queued", "running"}:
        return False
    updated_at = str(action.get("updated_at") or "").strip()
    if not updated_at:
        return True
    try:
        parsed = datetime.fromisoformat(updated_at)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    age = datetime.now(UTC) - parsed.astimezone(UTC)
    return age.total_seconds() > max_age_seconds


def _ordered_scenes(scenes: list[Any]) -> list[Any]:
    return sorted(scenes, key=lambda scene: int(getattr(scene, "scene_number", 0) or 0))


def _asset_url(storage_uri: str) -> str:
    settings_factory = _page_attr("get_settings")
    return _visual_asset_url(storage_uri, settings_factory().local_storage_path)


async def _save_script_from_ui(
    project_id: UUID,
    script_id: UUID,
    title: str,
    content: str,
) -> None:
    await save_script_from_ui(project_id, script_id, title, content)


def _render_script_area(project_id: UUID, summary: dict[str, Any]) -> None:
    render_script_area(
        project_id,
        summary,
        project_ai_action=_project_ai_action,
        ai_action_is_stale=_ai_action_is_stale,
        loading_dialog_factory=_page_attr("_generation_loading_dialog"),
        retry_initial_script_from_ui=_page_attr("_retry_initial_script_from_ui"),
        section_title=_section_title,
    )


def _render_assets_area(project_id: UUID, summary: dict[str, Any]) -> None:
    render_assets_area(
        project_id,
        summary,
        section_title=_section_title,
        loading_dialog_factory=_page_attr("_generation_loading_dialog"),
    )


def _render_storyboard_area(project_id: UUID, summary: dict[str, Any]) -> None:
    render_storyboard_area(
        project_id,
        summary,
        section_title=_section_title,
        loading_dialog_factory=_page_attr("_generation_loading_dialog"),
    )


def _render_video_area(project_id: UUID, summary: dict[str, Any]) -> None:
    render_video_area(
        project_id,
        summary,
        section_title=_section_title,
        loading_dialog_factory=_page_attr("_generation_loading_dialog"),
    )


def register_ui_pages() -> None:
    register_home_pages(
        body_style=_page_attr("_body_style"),
        project_cards=_page_attr("_project_cards"),
        render_project_card=_page_attr("_render_project_card"),
        create_project_from_chat_prompt=_page_attr("_create_project_from_chat_prompt"),
        create_project_from_idea=_page_attr("_create_project_from_idea"),
        delete_lab_idea_from_ui=_page_attr("_delete_lab_idea_from_ui"),
        loading_dialog_factory=_page_attr("_generation_loading_dialog"),
        clean_idea_title=_page_attr("_clean_idea_title"),
        home_sidebar=_page_attr("_home_sidebar"),
        studio_logo=_page_attr("_studio_logo"),
        theme_toggle=_page_attr("_theme_toggle"),
        user_avatar=_page_attr("_user_avatar"),
    )
    register_settings_page(
        body_style=_page_attr("_body_style"),
        settings_tab_key=_page_attr("_settings_tab_key"),
        project_cards=_page_attr("_project_cards"),
        home_sidebar=_page_attr("_home_sidebar"),
        theme_toggle=_page_attr("_theme_toggle"),
        user_avatar=_page_attr("_user_avatar"),
        save_avatar_file=_page_attr("_save_avatar_file"),
        purge_application_data_from_ui=_page_attr("_purge_application_data_from_ui"),
        purge_all_ideas_from_ui=_page_attr("_purge_all_ideas_from_ui"),
        purge_all_projects_from_ui=_page_attr("_purge_all_projects_from_ui"),
    )
    register_project_workspace_pages(
        body_style=_page_attr("_body_style"),
        project_summary=_page_attr("_project_summary"),
        workspace_section_access=_page_attr("_workspace_section_access"),
        first_available_workspace_section=_page_attr("_first_available_workspace_section"),
        workspace_header=_page_attr("_workspace_header"),
        render_script_area=_page_attr("_render_script_area"),
        render_assets_area=_page_attr("_render_assets_area"),
        render_storyboard_area=_page_attr("_render_storyboard_area"),
        render_video_area=_page_attr("_render_video_area"),
        assistant_panel=_page_attr("_assistant_panel"),
    )
