from uuid import uuid4

import pytest

from app.core.enums import ArtifactStatus
from app.projects.versioning import resolve_stale_artifacts_after_regeneration
from app.workflows.dependencies import collect_dependent_artifacts


def test_collect_dependent_artifacts_walks_transitive_edges() -> None:
    briefing = uuid4()
    story_bible = uuid4()
    script = uuid4()
    storyboard = uuid4()

    stale = collect_dependent_artifacts(
        [
            (briefing, story_bible),
            (story_bible, script),
            (script, storyboard),
        ],
        {briefing},
    )

    assert stale == {story_bible, script, storyboard}


def test_collect_dependent_artifacts_skips_locked_nodes() -> None:
    script = uuid4()
    storyboard = uuid4()
    animatic = uuid4()

    stale = collect_dependent_artifacts(
        [
            (script, storyboard),
            (storyboard, animatic),
        ],
        {script},
        locked_artifact_ids={storyboard},
    )

    assert stale == set()


@pytest.mark.asyncio
async def test_resolve_stale_artifacts_after_regeneration_cancels_stale_artifacts() -> None:
    project_id = uuid4()
    stale_artifact = type(
        "Artifact",
        (),
        {"project_id": project_id, "status": ArtifactStatus.STALE},
    )()
    ready_artifact = type(
        "Artifact",
        (),
        {"project_id": project_id, "status": ArtifactStatus.READY_FOR_REVIEW},
    )()

    class FakeScalarResult:
        def __iter__(self) -> object:
            return iter([stale_artifact])

    class FakeResult:
        def scalars(self) -> FakeScalarResult:
            return FakeScalarResult()

    class FakeSession:
        flushed = False
        committed = False

        async def execute(self, statement: object) -> FakeResult:
            return FakeResult()

        async def flush(self) -> None:
            self.flushed = True

        async def commit(self) -> None:
            self.committed = True

    session = FakeSession()

    resolved = await resolve_stale_artifacts_after_regeneration(
        session,  # type: ignore[arg-type]
        project_id,
    )

    assert resolved == 1
    assert stale_artifact.status == ArtifactStatus.CANCELLED
    assert ready_artifact.status == ArtifactStatus.READY_FOR_REVIEW
    assert session.flushed is True
    assert session.committed is True
