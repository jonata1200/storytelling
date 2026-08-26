import pytest

from app.core.enums import ProjectStatus
from app.workflows.state_machine import assert_project_transition, can_transition_project


def test_project_state_machine_allows_forward_step() -> None:
    assert can_transition_project(ProjectStatus.DRAFT, ProjectStatus.IDEA_GENERATION)


def test_project_state_machine_rejects_skipped_step() -> None:
    assert not can_transition_project(ProjectStatus.DRAFT, ProjectStatus.SCRIPT_GENERATION)
    with pytest.raises(ValueError):
        assert_project_transition(ProjectStatus.DRAFT, ProjectStatus.SCRIPT_GENERATION)
