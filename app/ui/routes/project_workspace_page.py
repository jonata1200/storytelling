# ruff: noqa: E501

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from nicegui import ui

from app.projects.models import Project

BodyStyle = Callable[[], None]
ProjectSummaryLoader = Callable[[UUID, str], Awaitable[dict[str, Any] | None]]
WorkspaceAccessChecker = Callable[[str, dict[str, int], object], tuple[bool, str]]
WorkspaceFallbackResolver = Callable[[dict[str, int], object], str]
WorkspaceHeaderRenderer = Callable[[Project, str, dict[str, int], object], None]
WorkspaceAreaRenderer = Callable[[UUID, dict[str, Any]], None]

# Seções válidas do workspace. A etapa de finalização foi removida.
WORKSPACE_ROUTE_SECTIONS = ("script", "visual", "storyboard")


def register_project_workspace_pages(
    *,
    body_style: BodyStyle,
    project_summary: ProjectSummaryLoader,
    workspace_section_access: WorkspaceAccessChecker,
    first_available_workspace_section: WorkspaceFallbackResolver,
    workspace_header: WorkspaceHeaderRenderer,
    render_script_area: WorkspaceAreaRenderer,
    render_visual_bible_area: WorkspaceAreaRenderer,
    render_storyboard_area: WorkspaceAreaRenderer,
) -> None:
    @ui.page("/projects/{project_id}", response_timeout=60)
    async def project_workspace(project_id: str) -> None:
        ui.navigate.to(f"/projects/{project_id}/script")
        return

    @ui.page("/projects/{project_id}/{section}", response_timeout=60)
    async def project_studio(project_id: str, section: str) -> None:
        body_style()
        if section == "video":
            ui.navigate.to(f"/projects/{project_id}/storyboard")
            return
        if section not in WORKSPACE_ROUTE_SECTIONS:
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
        production_settings = summary.get("production_settings")
        workflow_mode = getattr(production_settings, "workflow_mode", None)
        allowed, reason = workspace_section_access(section, counts, workflow_mode)
        if not allowed:
            fallback = first_available_workspace_section(counts, workflow_mode)
            ui.notify(reason, color="warning")
            ui.navigate.to(f"/projects/{project_id}/{fallback}")
            return
        workspace_header(project, section, counts, workflow_mode)
        with ui.element("div").classes(
            "workspace-layout flex w-full items-start flex-nowrap gap-0"
        ):
            with ui.column().classes(
                "workspace-main flex-1 min-w-0 p-8 lg:p-10 gap-4 h-[calc(100vh-64px)] overflow-y-auto"
            ):
                if section == "script":
                    render_script_area(project_uuid, summary)
                elif section == "visual":
                    render_visual_bible_area(project_uuid, summary)
                elif section == "storyboard":
                    render_storyboard_area(project_uuid, summary)