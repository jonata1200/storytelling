from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from app.projects import service as project_service


class _FakeProjectRepository:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def get_project(self, project_id: object) -> object | None:
        if self.session.project.id == project_id:
            return cast(object, self.session.project)
        return None


class _FakeSession:
    def __init__(self, project: object) -> None:
        self.project = project
        self.added: list[Any] = []
        self.commits = 0
        self.refreshed: list[object] = []

    async def get(self, model: object, item_id: object, **kwargs: Any) -> object | None:
        if getattr(self.project, "id", None) == item_id:
            return self.project
        return None

    def add(self, item: object) -> None:
        self.added.append(item)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, item: object) -> None:
        self.refreshed.append(item)


async def _not_locked(_session: Any, _project_id: Any) -> bool:
    return False


@pytest.mark.asyncio
async def test_sync_project_title_updates_title_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    project = SimpleNamespace(
        id=project_id,
        title="Crie a historia de um bombeiro",
        description="prompt original",
        current_version=1,
        deleted_at=None,
    )
    session = _FakeSession(project)
    monkeypatch.setattr(project_service, "ProjectRepository", _FakeProjectRepository)
    monkeypatch.setattr(project_service, "_project_title_is_locked", _not_locked)

    synced = await project_service.sync_project_title(
        session,  # type: ignore[arg-type]
        project_id,
        "O Último Resgate",
        change_note="Project title synchronized from script title",
    )
    synced_again = await project_service.sync_project_title(
        session,  # type: ignore[arg-type]
        project_id,
        "O Último Resgate",
        change_note="Project title synchronized from script title",
    )

    assert synced is project
    assert synced_again is project
    assert project.title == "O Último Resgate"
    assert project.current_version == 2
    assert session.commits == 1
    assert session.refreshed == [project]
    assert len(session.added) == 1
    version = session.added[0]
    assert version.project_id == project_id
    assert version.version_number == 2
    assert version.snapshot["title"] == "O Último Resgate"
    assert version.change_note == "Project title synchronized from script title"
