from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects.service import (
    delete_all_projects,
    hard_delete_all_story_ideas,
    hard_delete_project,
    purge_application_data,
)


class _FakeScalarResult:
    def __init__(self, projects: list[SimpleNamespace]) -> None:
        self._projects = projects

    def scalars(self) -> "_FakeScalarResult":
        return self

    def __iter__(self) -> Any:
        return iter(self._projects)


class _FakeSession:
    def __init__(self, projects: list[SimpleNamespace]) -> None:
        self.projects = projects
        self.committed = False

    async def execute(self, statement: Any) -> _FakeScalarResult:
        return _FakeScalarResult(self.projects)

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_delete_all_projects_marks_active_projects_deleted() -> None:
    projects = [SimpleNamespace(deleted_at=None), SimpleNamespace(deleted_at=None)]
    session = _FakeSession(projects)

    deleted_count = await delete_all_projects(cast(AsyncSession, session))

    assert deleted_count == 2
    assert session.committed is True
    assert all(isinstance(project.deleted_at, datetime) for project in projects)


class _FakePurgeSession:
    def __init__(self) -> None:
        self.scalar_calls = 0
        self.executed: list[str] = []
        self.committed = False

    async def scalar(self, statement: Any) -> int:
        self.scalar_calls += 1
        return self.scalar_calls

    async def execute(self, statement: Any) -> None:
        self.executed.append(str(statement))

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_purge_application_data_truncates_project_graph() -> None:
    session = _FakePurgeSession()

    counts = await purge_application_data(cast(AsyncSession, session))

    assert counts["projects"] == 1
    assert counts["prompt_executions"] == 8
    assert session.executed == ["TRUNCATE TABLE projects RESTART IDENTITY CASCADE"]
    assert session.committed is True


class _FakeHardDeleteSession:
    def __init__(self, project_count: int = 1) -> None:
        self.project_count = project_count
        self.scalar_calls = 0
        self.executed: list[str] = []
        self.committed = False
        self.rolled_back = False

    async def scalar(self, statement: Any) -> int:
        self.scalar_calls += 1
        if "tmp_target_projects" in str(statement):
            return self.project_count
        return self.scalar_calls

    async def execute(self, statement: Any, params: Any | None = None) -> None:
        self.executed.append(str(statement))

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.asyncio
async def test_hard_delete_project_removes_project_graph_physically() -> None:
    session = _FakeHardDeleteSession()

    deleted = await hard_delete_project(
        cast(AsyncSession, session),
        "62d6bfdf-d2e3-4b8b-93de-b5f4f764f474",
    )

    assert deleted is True
    assert any("CREATE TEMP TABLE tmp_target_projects" in sql for sql in session.executed)
    assert any("DELETE FROM projects" in sql for sql in session.executed)
    assert all("deleted_at" not in sql for sql in session.executed)
    assert session.committed is True


@pytest.mark.asyncio
async def test_hard_delete_project_rolls_back_when_project_is_missing() -> None:
    session = _FakeHardDeleteSession(project_count=0)

    deleted = await hard_delete_project(
        cast(AsyncSession, session),
        "62d6bfdf-d2e3-4b8b-93de-b5f4f764f474",
    )

    assert deleted is False
    assert session.rolled_back is True
    assert session.committed is False


@pytest.mark.asyncio
async def test_hard_delete_all_story_ideas_removes_db_ideas_and_non_briefing_artifacts() -> None:
    session = _FakeHardDeleteSession()

    counts = await hard_delete_all_story_ideas(cast(AsyncSession, session))

    assert counts["story_ideas"] == 3
    assert any("TRUNCATE TABLE" in sql and "story_ideas" in sql for sql in session.executed)
    assert any("artifact_type <> 'BRIEFING'" in sql for sql in session.executed)
    assert all("TRUNCATE TABLE projects" not in sql for sql in session.executed)
    assert session.committed is True
