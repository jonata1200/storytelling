"""Testes do progresso do pop-up de geração de referências visuais."""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.ui.workspace import visual_bible_area
from app.ui.workspace.visual_reference_state import (
    VisualReferencePollStatus,
    visual_reference_batch_progress,
)


def _key(kind: str, target: str) -> tuple[str, str, str]:
    return (
        "character" if kind == "c" else "location",
        target,
        "full_body" if kind == "c" else "establishing",
    )


def test_batch_progress_counts_completed_of_requested() -> None:
    completed = {_key("c", "clara"), _key("c", "vitor"), _key("l", "outro")}
    requested = {_key("c", "clara"), _key("c", "vitor"), _key("l", "estacao")}

    done, total, _label = visual_reference_batch_progress(completed, set(), requested)

    assert (done, total) == (2, 3)


def test_batch_progress_labels_active_kind() -> None:
    completed = {_key("c", "clara")}
    active = {_key("l", "estacao")}

    done, total, label = visual_reference_batch_progress(
        completed, active, {_key("c", "clara"), _key("l", "estacao")}
    )

    assert (done, total) == (1, 2)
    assert label == "local"


def test_batch_progress_labels_active_character() -> None:
    done, _total, label = visual_reference_batch_progress(
        set(), {_key("c", "clara")}, {_key("c", "clara")}
    )

    assert done == 0
    assert label == "personagem"


def test_batch_progress_empty_batch_is_zeroed() -> None:
    assert visual_reference_batch_progress(set(), set(), set()) == (0, 0, "")


@pytest.mark.asyncio
async def test_watcher_reports_progress_to_dialog_updater() -> None:
    client = SimpleNamespace(is_deleted=False)
    states = iter(
        [
            VisualReferencePollStatus(False, True, None, completed=1, total=3, active_kind="local"),
            VisualReferencePollStatus(True, False),
        ]
    )
    captured: list[VisualReferencePollStatus] = []
    navigations: list[Any] = []

    async def poll_state(*_: object) -> VisualReferencePollStatus:
        return next(states)

    async def no_wait(_: float) -> None:
        return None

    await visual_bible_area._watch_visual_reference_generation(
        uuid4(),
        frozenset(),
        client,
        poll_state=poll_state,
        sleep=no_wait,
        navigate=lambda *_: navigations.append(1),
        on_progress=lambda _client, status: captured.append(status),
    )

    assert len(captured) == 1
    assert captured[0].completed == 1
    assert captured[0].total == 3
    assert captured[0].active_kind == "local"
    assert len(navigations) == 1


@pytest.mark.asyncio
async def test_watcher_skips_progress_when_batch_total_unknown() -> None:
    client = SimpleNamespace(is_deleted=False)
    updates: list[int] = []

    async def mark_deleted_during_wait(_: float) -> None:
        client.is_deleted = True

    async def poll_state(*_: object) -> VisualReferencePollStatus:
        return VisualReferencePollStatus(False, True)

    await visual_bible_area._watch_visual_reference_generation(
        uuid4(),
        frozenset(),
        client,
        poll_state=poll_state,
        sleep=mark_deleted_during_wait,
        navigate=lambda *_: None,
        on_progress=lambda *_: updates.append(1),
    )

    assert updates == []