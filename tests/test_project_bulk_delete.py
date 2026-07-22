from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects.service import delete_all_projects, purge_application_data


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
