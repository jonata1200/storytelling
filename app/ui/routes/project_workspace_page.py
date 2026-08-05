# ruff: noqa: E501

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from nicegui import ui

from app.projects.models import Project

BodyStyle = Callable[[], None]
ProjectSummaryLoader = Callable[[UUID, str], Awaitable[dict[str, Any] | None]]
WorkspaceAccessChecker = Callable[[str, dict[str, int]], tuple[bool, str]]
WorkspaceFallbackResolver = Callable[[dict[str, int]], str]
WorkspaceHeaderRenderer = Callable[[Project, str, dict[str, int]], None]
WorkspaceAreaRenderer = Callable[[UUID, dict[str, Any]], None]
AssistantPanelRenderer = Callable[[UUID, str, dict[str, Any]], None]


def register_project_workspace_pages(
    *,
    body_style: BodyStyle,
    project_summary: ProjectSummaryLoader,
    workspace_section_access: WorkspaceAccessChecker,
    first_available_workspace_section: WorkspaceFallbackResolver,
    workspace_header: WorkspaceHeaderRenderer,
    render_script_area: WorkspaceAreaRenderer,
    render_assets_area: WorkspaceAreaRenderer,
    render_storyboard_area: WorkspaceAreaRenderer,
    render_video_area: WorkspaceAreaRenderer,
    render_finalization_area: WorkspaceAreaRenderer,
    render_dubbing_area: WorkspaceAreaRenderer,
    assistant_panel: AssistantPanelRenderer,
) -> None:
    @ui.page("/projects/{project_id}", response_timeout=15)
    async def project_workspace(project_id: str) -> None:
        ui.navigate.to(f"/projects/{project_id}/script")
        return

    @ui.page("/projects/{project_id}/{section}", response_timeout=15)
    async def project_studio(project_id: str, section: str) -> None:
        body_style()
        if section not in {"script", "assets", "storyboard", "video", "finalization", "dubbing"}:
            ui.navigate.to(f"/projects/{project_id}/script")
            return
        try:
            project_uuid = UUID(project_id)
            summary = await project_summary(project_uuid, section)
        except (ValueError, TypeError):
            summary = None
        if summary is None:
            with ui.column().classes("w-full min-h-screen items-center justify-center gap-4"):
                ui.icon("movie_off").classes("text-6xl acid")
                ui.label("Projeto não encontrado").classes("brand-type text-3xl font-bold")
                ui.button("Voltar ao início", on_click=lambda: ui.navigate.to("/")).classes(
                    "acid-bg"
                )
            return
        project: Project = summary["project"]
        counts: dict[str, int] = summary["counts"]
        allowed, reason = workspace_section_access(section, counts)
        if not allowed:
            fallback = first_available_workspace_section(counts)
            ui.notify(reason, color="warning")
            ui.navigate.to(f"/projects/{project_id}/{fallback}")
            return
        workspace_header(project, section, counts)
        with ui.element("div").classes(
            "workspace-layout flex w-full items-start flex-nowrap gap-0"
        ):
            with ui.column().classes(
                "workspace-main flex-1 min-w-0 p-8 lg:p-10 gap-4 h-[calc(100vh-64px)] overflow-y-auto"
            ):
                if section == "script":
                    render_script_area(project_uuid, summary)
                elif section == "assets":
                    render_assets_area(project_uuid, summary)
                elif section == "storyboard":
                    render_storyboard_area(project_uuid, summary)
                elif section == "video":
                    render_video_area(project_uuid, summary)
                elif section == "finalization":
                    render_finalization_area(project_uuid, summary)
                elif section == "dubbing":
                    render_dubbing_area(project_uuid, summary)
            assistant_panel(project_uuid, section, summary)
