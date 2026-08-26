from app.core.enums import ProjectStatus
from app.projects.models import Project

PROJECT_TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
    ProjectStatus.DRAFT: {ProjectStatus.IDEA_GENERATION, ProjectStatus.ARCHIVED},
    ProjectStatus.IDEA_GENERATION: {ProjectStatus.IDEA_APPROVAL, ProjectStatus.FAILED},
    ProjectStatus.IDEA_APPROVAL: {
        ProjectStatus.STORY_DESIGN,
        ProjectStatus.IDEA_GENERATION,
        ProjectStatus.ARCHIVED,
    },
    ProjectStatus.STORY_DESIGN: {ProjectStatus.STORY_APPROVAL, ProjectStatus.FAILED},
    ProjectStatus.STORY_APPROVAL: {ProjectStatus.SCRIPT_GENERATION, ProjectStatus.STORY_DESIGN},
    ProjectStatus.SCRIPT_GENERATION: {ProjectStatus.SCRIPT_APPROVAL, ProjectStatus.FAILED},
    ProjectStatus.SCRIPT_APPROVAL: {
        ProjectStatus.VISUAL_BIBLE_GENERATION,
        ProjectStatus.SCRIPT_GENERATION,
    },
    ProjectStatus.VISUAL_BIBLE_GENERATION: {
        ProjectStatus.VISUAL_BIBLE_APPROVAL,
        ProjectStatus.FAILED,
    },
    ProjectStatus.VISUAL_BIBLE_APPROVAL: {
        ProjectStatus.PRODUCTION_PLANNING,
        ProjectStatus.VISUAL_BIBLE_GENERATION,
    },
    ProjectStatus.PRODUCTION_PLANNING: {
        ProjectStatus.VIDEO_GENERATION,
    },
    ProjectStatus.VIDEO_GENERATION: {ProjectStatus.COMPLETED, ProjectStatus.FAILED},
    ProjectStatus.COMPLETED: {ProjectStatus.ARCHIVED},
    ProjectStatus.FAILED: {ProjectStatus.DRAFT, ProjectStatus.ARCHIVED},
    ProjectStatus.ARCHIVED: set(),
}


class WorkflowStateError(ValueError):
    pass


def can_transition_project(current: ProjectStatus, target: ProjectStatus) -> bool:
    return target in PROJECT_TRANSITIONS[current]


def assert_project_transition(current: ProjectStatus, target: ProjectStatus) -> None:
    if not can_transition_project(current, target):
        raise WorkflowStateError(f"Invalid project transition: {current} -> {target}")


def advance_project_status(project: Project, target: ProjectStatus) -> None:
    """Advance through valid forward transitions without bypassing the state machine."""
    if project.status == target:
        return
    queue: list[tuple[ProjectStatus, list[ProjectStatus]]] = [(project.status, [])]
    visited = {project.status}
    while queue:
        current, path = queue.pop(0)
        for candidate in PROJECT_TRANSITIONS[current]:
            if candidate in {ProjectStatus.FAILED, ProjectStatus.ARCHIVED} or candidate in visited:
                continue
            next_path = [*path, candidate]
            if candidate == target:
                for status in next_path:
                    assert_project_transition(project.status, status)
                    project.status = status
                return
            visited.add(candidate)
            queue.append((candidate, next_path))
    raise WorkflowStateError(f"Cannot advance project from {project.status} to {target}")
