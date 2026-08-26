from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.core.enums import GenerationJobStatus
from app.ui.workspace import video_reference_state
from app.ui.workspace.video_reference_state import (
    VideoPollStatus,
    video_poll_decision,
)
from app.video_generation.models import ContinuousVideoSegment, GenerationJob


def _job(status: GenerationJobStatus, *, error: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        request_payload={"operation": "generate_shot"},
        error=error,
    )


def _segment(*, video_asset_id: Any = None) -> SimpleNamespace:
    return SimpleNamespace(generated_video_asset_id=video_asset_id)


def test_video_poll_decision_detects_new_video_and_active_generation() -> None:
    known = frozenset({"asset-1"})
    jobs = [_job(GenerationJobStatus.RUNNING)]
    segments = [_segment(video_asset_id="asset-1"), _segment(video_asset_id="asset-2")]

    has_new, has_active = video_poll_decision(known, jobs, segments)

    assert has_new is True
    assert has_active is True


def test_video_poll_decision_ignores_known_assets() -> None:
    known = frozenset({"asset-1", "asset-2"})
    jobs = [_job(GenerationJobStatus.SUCCEEDED)]
    segments = [_segment(video_asset_id="asset-1"), _segment(video_asset_id="asset-2")]

    has_new, has_active = video_poll_decision(known, jobs, segments)

    assert has_new is False
    assert has_active is False


def test_video_poll_decision_reports_failure_error() -> None:
    known = frozenset()
    jobs = [_job(GenerationJobStatus.FAILED, error="O Vibes falhou")]
    segments = [_segment()]

    has_new, has_active = video_poll_decision(known, jobs, segments)

    assert has_new is False
    assert has_active is False


@pytest.mark.asyncio
async def test_watch_video_generation_reloads_on_new_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, str | None]] = []
    errors: list[str] = []

    async def poll_state(project_id: object, known: object) -> VideoPollStatus:
        _ = project_id, known
        return VideoPollStatus(True, False)

    def navigate(client: Any, target: str | None) -> None:
        calls.append((client, target))

    async def show_error(client: Any, error: str) -> None:
        errors.append(error)

    async def sleep(_seconds: float) -> None:
        return None

    client = SimpleNamespace(id="client-1", is_deleted=False)
    await video_reference_state._watch_video_generation(
        uuid4(),
        frozenset(),
        client,
        poll_state=lambda *_args: _poll(VideoPollStatus(True, False)),
        sleep=sleep,
        navigate=navigate,
        show_error=show_error,
    )

    # O watcher NÃO recarrega quando o lote termina: a task da UI
    # (_wait_for_video_generation_jobs) mostra o popup de resultado e recarrega
    # — recarga duplicada derrubava o websocket ("conexão perdida") e travava
    # a página re-baixando os vídeos das variantes.
    assert calls == []
    assert errors == []


@pytest.mark.asyncio
async def test_watch_video_generation_stops_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = monkeypatch
    calls: list[tuple[Any, str | None]] = []

    async def sleep(_seconds: float) -> None:
        return None

    client = SimpleNamespace(id="client-1", is_deleted=False)
    await video_reference_state._watch_video_generation(
        uuid4(),
        frozenset(),
        client,
        poll_state=lambda *_args: _poll(VideoPollStatus(False, False, "falhou")),
        sleep=sleep,
        navigate=lambda current_client, target: calls.append((current_client, target)),
        show_error=lambda *_args, **_kwargs: None,
    )

    assert calls == []


@pytest.mark.asyncio
async def test_watch_video_generation_ends_without_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, str | None]] = []

    async def sleep(_seconds: float) -> None:
        return None

    client = SimpleNamespace(id="client-1", is_deleted=False)
    await video_reference_state._watch_video_generation(
        uuid4(),
        frozenset(),
        client,
        poll_state=lambda *_args: _poll(VideoPollStatus(False, False)),
        sleep=sleep,
        navigate=lambda current_client, target: calls.append((current_client, target)),
        show_error=lambda *_args, **_kwargs: None,
    )

    assert calls == []


def test_video_poll_decision_type_helpers_use_job_payload() -> None:
    job = GenerationJob.__new__(GenerationJob)
    _ = job
    segment = ContinuousVideoSegment.__new__(ContinuousVideoSegment)
    _ = segment
    # Cobertura da assinatura exportada para uso no workspace.
    has_new, has_active = video_poll_decision(frozenset(), [], [])
    assert has_new is False
    assert has_active is False


# ---------------------------------------------------------------------------
# Frame watcher (inicial/final de um segmento)
# ---------------------------------------------------------------------------


def _frame_segment(
    *,
    initial_asset_id: Any = None,
    final_asset_id: Any = None,
    metadata: dict[str, Any] | None = None,
    status: Any = "RUNNING",
) -> SimpleNamespace:
    return SimpleNamespace(
        source_frame_asset_id=initial_asset_id,
        final_frame_asset_id=final_asset_id,
        metadata_json=metadata or {},
        status=status,
    )


def test_frame_poll_decision_detects_new_initial_frame() -> None:
    segment = _frame_segment(initial_asset_id="frame-2")

    status = video_reference_state.frame_poll_decision(segment, "initial", "frame-1")

    assert status.completed is True
    assert status.failed is False


def test_frame_poll_decision_ignores_known_initial_frame() -> None:
    segment = _frame_segment(initial_asset_id="frame-1")

    status = video_reference_state.frame_poll_decision(segment, "initial", "frame-1")

    assert status.completed is False
    assert status.failed is False


def test_frame_poll_decision_detects_failed_frame() -> None:
    segment = _frame_segment(
        metadata={
            "error": "Meta AI não apresentou uma nova imagem vertical em alta resolução.",
        },
        status="FAILED",
    )

    status = video_reference_state.frame_poll_decision(segment, "initial", "")

    assert status.failed is True
    assert "Meta AI não apresentou" in (status.error or "")


def test_frame_poll_decision_watches_final_frame_field() -> None:
    segment = _frame_segment(final_asset_id="final-9")

    status = video_reference_state.frame_poll_decision(segment, "final", "")

    assert status.completed is True


@pytest.mark.asyncio
async def test_watch_frame_generation_navigates_on_completion() -> None:
    calls: list[tuple[Any, str | None]] = []

    async def sleep(_seconds: float) -> None:
        return None

    client = SimpleNamespace(id="client-1", is_deleted=False)
    await video_reference_state._watch_frame_generation(
        uuid4(),
        uuid4(),
        "initial",
        "",
        client,
        poll_state=lambda *_args: _poll_frame(
            video_reference_state.FramePollStatus(completed=True, failed=False)
        ),
        sleep=sleep,
        navigate=lambda current_client, target: calls.append((current_client, target)),
        show_error=lambda *_args, **_kwargs: None,
    )

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_watch_frame_generation_reports_failure_and_stops() -> None:
    errors: list[str] = []
    navigations: list[Any] = []

    async def sleep(_seconds: float) -> None:
        return None

    client = SimpleNamespace(id="client-1", is_deleted=False)
    await video_reference_state._watch_frame_generation(
        uuid4(),
        uuid4(),
        "initial",
        "",
        client,
        poll_state=lambda *_args: _poll_frame(
            video_reference_state.FramePollStatus(
                completed=False, failed=True, error="timeout na geração"
            )
        ),
        sleep=sleep,
        navigate=lambda current_client, _target: navigations.append(current_client),
        show_error=lambda current_client, error: errors.append(error),
    )

    assert errors == ["timeout na geração"]
    assert len(navigations) == 1


async def _poll_frame(status: Any) -> Any:
    return status


async def _poll(status: VideoPollStatus) -> VideoPollStatus:
    return status