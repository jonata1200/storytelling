from app.core.enums import ProjectStatus

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
        ProjectStatus.STORYBOARD_GENERATION,
        ProjectStatus.VISUAL_BIBLE_GENERATION,
    },
    ProjectStatus.STORYBOARD_GENERATION: {ProjectStatus.STORYBOARD_APPROVAL, ProjectStatus.FAILED},
    ProjectStatus.STORYBOARD_APPROVAL: {
        ProjectStatus.PRODUCTION_PLANNING,
        ProjectStatus.STORYBOARD_GENERATION,
    },
    ProjectStatus.PRODUCTION_PLANNING: {
        ProjectStatus.VIDEO_GENERATION,
        ProjectStatus.STORYBOARD_APPROVAL,
    },
    ProjectStatus.VIDEO_GENERATION: {ProjectStatus.VIDEO_REVIEW, ProjectStatus.FAILED},
    ProjectStatus.VIDEO_REVIEW: {ProjectStatus.AUDIO_GENERATION, ProjectStatus.VIDEO_GENERATION},
    ProjectStatus.AUDIO_GENERATION: {ProjectStatus.ASSEMBLY, ProjectStatus.FAILED},
    ProjectStatus.ASSEMBLY: {ProjectStatus.QUALITY_CONTROL, ProjectStatus.FAILED},
    ProjectStatus.QUALITY_CONTROL: {ProjectStatus.FINAL_APPROVAL, ProjectStatus.ASSEMBLY},
    ProjectStatus.FINAL_APPROVAL: {ProjectStatus.COMPLETED, ProjectStatus.QUALITY_CONTROL},
    ProjectStatus.COMPLETED: {ProjectStatus.ARCHIVED},
    ProjectStatus.FAILED: {ProjectStatus.DRAFT, ProjectStatus.ARCHIVED},
    ProjectStatus.ARCHIVED: set(),
}


def can_transition_project(current: ProjectStatus, target: ProjectStatus) -> bool:
    return target in PROJECT_TRANSITIONS[current]


def assert_project_transition(current: ProjectStatus, target: ProjectStatus) -> None:
    if not can_transition_project(current, target):
        raise ValueError(f"Invalid project transition: {current} -> {target}")
