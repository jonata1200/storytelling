from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects import service as project_service
from app.projects.service import (
    delete_all_projects,
    hard_delete_all_story_ideas,
    hard_delete_project,
    hard_delete_story_idea_by_payload_id_status,
    purge_application_data,
)


def _record_deleted_storage_uris(target: list[str], storage_uris: list[str]) -> int:
    target.extend(storage_uris)
    return len(storage_uris)


def _record_deleted_project_dirs(target: list[UUID], project_ids: list[UUID]) -> int:
    target.extend(project_ids)
    return len(project_ids)


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
        self.project_id = UUID("62d6bfdf-d2e3-4b8b-93de-b5f4f764f474")
        self.scalar_calls = 0
        self.executed: list[str] = []
        self.committed = False

    async def scalar(self, statement: Any) -> int:
        self.scalar_calls += 1
        return self.scalar_calls

    async def execute(self, statement: Any) -> Any:
        sql = str(statement)
        if "projects.id" in sql:
            return SimpleNamespace(all=lambda: [(self.project_id,)])
        if "asset_versions.storage_uri" in sql:
            return SimpleNamespace(all=lambda: [("storage/project-image-v1.png",)])
        if "assets.storage_uri" in sql:
            return SimpleNamespace(all=lambda: [("storage/project-image.png",)])
        self.executed.append(sql)
        return SimpleNamespace(all=lambda: [])

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_purge_application_data_truncates_project_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakePurgeSession()
    deleted_storage_uris: list[str] = []
    deleted_project_ids: list[UUID] = []
    monkeypatch.setattr(
        project_service,
        "delete_local_storage_files",
        lambda storage_uris: _record_deleted_storage_uris(deleted_storage_uris, storage_uris),
    )
    monkeypatch.setattr(
        project_service,
        "delete_project_storage_dirs",
        lambda project_ids: _record_deleted_project_dirs(deleted_project_ids, project_ids),
    )

    counts = await purge_application_data(cast(AsyncSession, session))

    assert counts["projects"] == 1
    assert counts["prompt_executions"] == 8
    assert counts["storage_files"] == 3
    assert deleted_storage_uris == ["storage/project-image.png", "storage/project-image-v1.png"]
    assert deleted_project_ids == [session.project_id]
    assert session.executed == ["TRUNCATE TABLE projects RESTART IDENTITY CASCADE"]
    assert session.committed is True


class _FakeHardDeleteSession:
    def __init__(
        self,
        project_count: int = 1,
        project_ids: list[UUID] | None = None,
        storage_rows: list[tuple[str | None]] | None = None,
        asset_version_storage_rows: list[tuple[str | None]] | None = None,
    ) -> None:
        self.project_count = project_count
        self.project_ids = project_ids or []
        self.storage_rows = storage_rows or []
        self.asset_version_storage_rows = asset_version_storage_rows or []
        self.scalar_calls = 0
        self.executed: list[str] = []
        self.committed = False
        self.rolled_back = False

    async def scalar(self, statement: Any) -> int:
        self.scalar_calls += 1
        if "tmp_target_projects" in str(statement):
            return self.project_count
        return self.scalar_calls

    async def execute(self, statement: Any, params: Any | None = None) -> Any:
        sql = str(statement)
        self.executed.append(sql)
        if "asset_versions.storage_uri" in sql:
            return SimpleNamespace(all=lambda: self.asset_version_storage_rows)
        if (
            ("SELECT storage_uri" in sql or "assets.storage_uri" in sql)
            and "FROM assets" in sql
        ):
            return SimpleNamespace(all=lambda: self.storage_rows)
        if "SELECT id FROM tmp_target_projects" in sql:
            return SimpleNamespace(all=lambda: [(project_id,) for project_id in self.project_ids])
        return SimpleNamespace(all=lambda: [])

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.asyncio
async def test_hard_delete_project_removes_project_graph_physically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = UUID("62d6bfdf-d2e3-4b8b-93de-b5f4f764f474")
    session = _FakeHardDeleteSession(
        project_ids=[project_id],
        storage_rows=[("storage/frame.png",)],
        asset_version_storage_rows=[("storage/frame-v1.png",)],
    )
    deleted_storage_uris: list[str] = []
    deleted_project_ids: list[UUID] = []
    monkeypatch.setattr(
        project_service,
        "delete_local_storage_files",
        lambda storage_uris: _record_deleted_storage_uris(deleted_storage_uris, storage_uris),
    )
    monkeypatch.setattr(
        project_service,
        "delete_project_storage_dirs",
        lambda project_ids: _record_deleted_project_dirs(deleted_project_ids, project_ids),
    )

    deleted = await hard_delete_project(cast(AsyncSession, session), project_id)

    assert deleted is True
    assert any("CREATE TEMP TABLE tmp_target_projects" in sql for sql in session.executed)
    assert any("DELETE FROM projects" in sql for sql in session.executed)
    continuous_segments_delete_index = next(
        index
        for index, sql in enumerate(session.executed)
        if "DELETE FROM continuous_video_segments" in sql
    )
    continuous_plans_delete_index = next(
        index
        for index, sql in enumerate(session.executed)
        if "DELETE FROM continuous_video_plans" in sql
    )
    generation_jobs_delete_index = next(
        index for index, sql in enumerate(session.executed) if "DELETE FROM generation_jobs" in sql
    )
    assets_delete_index = next(
        index for index, sql in enumerate(session.executed) if "DELETE FROM assets" in sql
    )
    assert continuous_segments_delete_index < generation_jobs_delete_index
    assert continuous_segments_delete_index < assets_delete_index
    assert continuous_plans_delete_index < generation_jobs_delete_index
    assert all("deleted_at" not in sql for sql in session.executed)
    assert deleted_storage_uris == ["storage/frame.png", "storage/frame-v1.png"]
    assert deleted_project_ids == [project_id]
    assert session.committed is True


@pytest.mark.asyncio
async def test_hard_delete_project_rolls_back_when_project_is_missing() -> None:
    session = _FakeHardDeleteSession(project_count=0)

    deleted = await hard_delete_project(
        cast(AsyncSession, session),
        UUID("62d6bfdf-d2e3-4b8b-93de-b5f4f764f474"),
    )

    assert deleted is False
    assert session.rolled_back is True
    assert session.committed is False


@pytest.mark.asyncio
async def test_hard_delete_all_story_ideas_removes_db_ideas_and_non_briefing_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeHardDeleteSession(storage_rows=[("storage/reference.png",)])
    deleted_storage_uris: list[str] = []
    monkeypatch.setattr(
        project_service,
        "delete_local_storage_files",
        lambda storage_uris: _record_deleted_storage_uris(deleted_storage_uris, storage_uris),
    )

    counts = await hard_delete_all_story_ideas(cast(AsyncSession, session))

    assert counts["story_ideas"] == 3
    assert counts["storage_files"] == 1
    assert deleted_storage_uris == ["storage/reference.png"]
    truncate_sql = next(sql for sql in session.executed if "TRUNCATE TABLE" in sql)
    assert "story_ideas" in truncate_sql
    assert "continuous_video_segments" in truncate_sql
    assert "continuous_video_plans" in truncate_sql
    assert any("artifact_type <> 'BRIEFING'" in sql for sql in session.executed)
    assert all("TRUNCATE TABLE projects" not in sql for sql in session.executed)
    assert session.committed is True


class _FakeStoryIdeaDeleteSession:
    def __init__(self, *, story_idea: Any | None, script_count: int = 0) -> None:
        self.story_idea = story_idea
        self.script_count = script_count
        self.scalar_calls = 0
        self.executed: list[str] = []
        self.committed = False

    async def scalar(self, statement: Any) -> Any:
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return self.story_idea
        return self.script_count

    async def execute(self, statement: Any, params: Any | None = None) -> Any:
        sql = str(statement)
        self.executed.append(sql)
        return SimpleNamespace(all=lambda: [])

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_hard_delete_story_idea_by_payload_id_reports_not_found() -> None:
    session = _FakeStoryIdeaDeleteSession(story_idea=None)

    status = await hard_delete_story_idea_by_payload_id_status(
        cast(AsyncSession, session),
        "idea-missing",
    )

    assert status == "not_found"
    assert session.executed == []
    assert session.committed is False


@pytest.mark.asyncio
async def test_hard_delete_story_idea_by_payload_id_reports_blocked_when_script_exists() -> None:
    story_idea = SimpleNamespace(
        id=UUID("62d6bfdf-d2e3-4b8b-93de-b5f4f764f474"),
        artifact_id=UUID("72d6bfdf-d2e3-4b8b-93de-b5f4f764f474"),
    )
    session = _FakeStoryIdeaDeleteSession(story_idea=story_idea, script_count=1)

    status = await hard_delete_story_idea_by_payload_id_status(
        cast(AsyncSession, session),
        "idea-linked",
    )

    assert status == "blocked"
    assert session.executed == []
    assert session.committed is False


@pytest.mark.asyncio
async def test_hard_delete_story_idea_by_payload_id_reports_deleted() -> None:
    story_idea = SimpleNamespace(
        id=UUID("62d6bfdf-d2e3-4b8b-93de-b5f4f764f474"),
        artifact_id=UUID("72d6bfdf-d2e3-4b8b-93de-b5f4f764f474"),
    )
    session = _FakeStoryIdeaDeleteSession(story_idea=story_idea)

    status = await hard_delete_story_idea_by_payload_id_status(
        cast(AsyncSession, session),
        "idea-free",
    )

    assert status == "deleted"
    assert any("DELETE FROM story_ideas" in sql for sql in session.executed)
    assert any("DELETE FROM artifacts" in sql for sql in session.executed)
    assert session.committed is True
