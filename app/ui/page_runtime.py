from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from nicegui import ui

from app.ui.routes.home_pages import register_home_pages
from app.ui.routes.project_workspace_page import register_project_workspace_pages
from app.ui.routes.settings_page import register_settings_page
from app.ui.shared import assistant_state
from app.ui.shared.page_config import play_completion_sound
from app.ui.visual.helpers import asset_url as _visual_asset_url
from app.ui.workspace.finalization_area import render_finalization_area
from app.ui.workspace.script_area import render_script_area, save_script_from_ui
from app.ui.workspace.storyboard_video_area import render_video_area
from app.ui.workspace.visual_bible_area import render_visual_bible_area

INITIAL_SCRIPT_PROGRESS_KEYS = ("scripts", "scenes", "shots", "characters", "frames", "clips")


class _PagesFacade(Protocol):
    """Fachada do módulo ``app.ui.pages`` usada pela camada de runtime.

    Tipada para que renomes de símbolos quebrem em tempo de análise (e não em runtime,
    como acontecia com a antiga ponte ``_page_attr`` via ``getattr`` por string).
    """

    nicegui_app: Any
    # get_settings é um wrapper lru_cache (Settings) — `Any` evita conflito de
    # variance com Protocol; os demais membros continuam estritamente tipados.
    get_settings: Any
    _body_style: Callable[..., Any]
    _project_cards: Callable[..., Any]
    _render_project_card: Callable[..., Any]
    _create_project_from_chat_prompt: Callable[..., Any]
    _create_project_from_idea: Callable[..., Any]
    _delete_lab_idea_from_ui: Callable[..., Any]
    _clean_idea_title: Callable[..., Any]
    _home_sidebar: Callable[..., Any]
    _studio_logo: Callable[..., Any]
    _theme_toggle: Callable[..., Any]
    _settings_tab_key: Callable[..., Any]
    _purge_application_data_from_ui: Callable[..., Any]
    _purge_all_ideas_from_ui: Callable[..., Any]
    _purge_all_projects_from_ui: Callable[..., Any]
    _show_ai_error_popup: Callable[..., Any]
    _generation_loading_dialog: Callable[..., Any]
    _retry_initial_script_from_ui: Callable[..., Any]
    _project_summary: Callable[..., Any]
    _workspace_section_access: Callable[..., Any]
    _first_available_workspace_section: Callable[..., Any]
    _workspace_header: Callable[..., Any]


_pages: _PagesFacade | None = None


def _ui_pages() -> _PagesFacade:
    if _pages is None:
        # Resolução lazy (import em tempo de chamada) evita import circular em
        # module-load e não depende da ordem de execução dos testes.
        from app.ui import pages as pages_module

        return pages_module
    return _pages


def _notify_ai_action_failure_once(project_id: UUID, summary: dict[str, Any]) -> None:
    _ = project_id
    ai_action = _project_ai_action(summary)
    if str(ai_action.get("status") or "") != "failed":
        return
    return


def _play_ai_action_completion_sound_once(project_id: UUID, ai_action: dict[str, Any]) -> None:
    if str(ai_action.get("status") or "") != "completed":
        return
    action = str(ai_action.get("action") or "ai_action")
    updated_at = str(ai_action.get("updated_at") or "")
    message = str(ai_action.get("message") or "")
    sound_key = f"{project_id}:{action}:{updated_at}:{message}"
    nicegui_app = _ui_pages().nicegui_app
    store = nicegui_app.storage.user.setdefault("heard_ai_completion_sounds", [])
    heard = [str(item) for item in store if isinstance(item, str)]
    if sound_key in heard:
        return
    heard.append(sound_key)
    nicegui_app.storage.user["heard_ai_completion_sounds"] = heard[-80:]
    play_completion_sound()


def _sync_ai_action_events_to_chat(project_id: UUID, summary_or_action: dict[str, Any]) -> None:
    nicegui_app = _ui_pages().nicegui_app
    assistant_state.nicegui_app = nicegui_app
    summary = summary_or_action if "production_settings" in summary_or_action else {}
    ai_action = (
        _project_ai_action(summary)
        if summary
        else summary_or_action
    )
    if summary:
        counts = summary.get("counts")
        count_map = counts if isinstance(counts, dict) else {}
        progressed_past_initial_script = any(
            _positive_count(count_map.get(key)) for key in INITIAL_SCRIPT_PROGRESS_KEYS
        )
        if progressed_past_initial_script:
            ai_action = dict(ai_action)
            ai_action["events"] = [
                event
                for event in ai_action.get("events", [])
                if not (
                    isinstance(event, dict)
                    and str(event.get("action") or "") == "create_initial_script"
                )
            ]
    assistant_state.sync_ai_action_events_to_chat(project_id, ai_action)
    _play_ai_action_completion_sound_once(project_id, ai_action)


def _positive_count(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        try:
            return int(value) > 0
        except ValueError:
            return False
    return False


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
    if not isinstance(action, dict):
        return {}
    normalized = dict(action)
    raw_events = normalized.get("events")
    if isinstance(raw_events, list):
        events: list[dict[str, Any]] = []
        for event in raw_events:
            if not isinstance(event, dict):
                continue
            events.append(dict(event))
        normalized["events"] = events
    return normalized


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
    return _visual_asset_url(storage_uri, _ui_pages().get_settings().local_storage_path)


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
        loading_dialog_factory=_ui_pages()._generation_loading_dialog,
        retry_initial_script_from_ui=_ui_pages()._retry_initial_script_from_ui,
        section_title=_section_title,
    )


def _render_video_area(project_id: UUID, summary: dict[str, Any]) -> None:
    render_video_area(
        project_id,
        summary,
        section_title=_section_title,
        loading_dialog_factory=_ui_pages()._generation_loading_dialog,
    )


def _render_finalization_area(project_id: UUID, summary: dict[str, Any]) -> None:
    render_finalization_area(project_id, summary)


def register_ui_pages(pages: _PagesFacade) -> None:
    global _pages
    _pages = pages
    register_home_pages(
        body_style=pages._body_style,
        project_cards=pages._project_cards,
        render_project_card=pages._render_project_card,
        create_project_from_chat_prompt=pages._create_project_from_chat_prompt,
        create_project_from_idea=pages._create_project_from_idea,
        delete_lab_idea_from_ui=pages._delete_lab_idea_from_ui,
        loading_dialog_factory=pages._generation_loading_dialog,
        clean_idea_title=pages._clean_idea_title,
        home_sidebar=pages._home_sidebar,
        studio_logo=pages._studio_logo,
        theme_toggle=pages._theme_toggle,
    )
    register_settings_page(
        body_style=pages._body_style,
        settings_tab_key=pages._settings_tab_key,
        project_cards=pages._project_cards,
        home_sidebar=pages._home_sidebar,
        theme_toggle=pages._theme_toggle,
        purge_application_data_from_ui=pages._purge_application_data_from_ui,
        purge_all_ideas_from_ui=pages._purge_all_ideas_from_ui,
        purge_all_projects_from_ui=pages._purge_all_projects_from_ui,
    )
    register_project_workspace_pages(
        body_style=pages._body_style,
        project_summary=pages._project_summary,
        workspace_section_access=pages._workspace_section_access,
        first_available_workspace_section=pages._first_available_workspace_section,
        workspace_header=pages._workspace_header,
        render_script_area=_render_script_area,
        render_visual_bible_area=render_visual_bible_area,
        render_video_area=_render_video_area,
        render_finalization_area=_render_finalization_area,
    )
