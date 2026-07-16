from uuid import uuid4

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
