from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.enums import GenerationJobStatus
from app.ui.workspace import storyboard_video_area
from app.video_generation.models import GenerationJob


def _job(status: GenerationJobStatus, *, error: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), status=status, progress=100, error=error)


def test_video_generation_outcome_reports_success() -> None:
    message, color = storyboard_video_area._video_generation_outcome(
        [_job(GenerationJobStatus.SUCCEEDED)]  # type: ignore[list-item]
    )

    assert message == "As opções de vídeo do Shot foram criadas com sucesso!"
    assert color == "positive"


def test_video_generation_outcome_reports_failure_detail() -> None:
    message, color = storyboard_video_area._video_generation_outcome(
        [_job(GenerationJobStatus.FAILED, error="provider indisponível")]  # type: ignore[list-item]
    )

    assert "Não foi possível gerar o vídeo" in message
    assert "provider indisponível" in message
    assert color == "negative"


@pytest.mark.asyncio
async def test_wait_for_video_jobs_tracks_until_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_id = uuid4()
    second_id = uuid4()
    reads = [
        {
            first_id: SimpleNamespace(
                id=first_id, status=GenerationJobStatus.RUNNING, progress=10
            ),
            second_id: SimpleNamespace(
                id=second_id, status=GenerationJobStatus.PENDING, progress=0
            ),
        },
        {
            first_id: SimpleNamespace(
                id=first_id, status=GenerationJobStatus.SUCCEEDED, progress=100
            ),
            second_id: SimpleNamespace(
                id=second_id,
                status=GenerationJobStatus.FAILED,
                progress=0,
                error="falhou",
            ),
        },
    ]
    state = {"read": 0}

    class FakeSession:
        async def get(self, _model: type[GenerationJob], job_id: object) -> object:
            return reads[state["read"]][job_id]  # type: ignore[index]

    class FakeSessionContext:
        async def __aenter__(self) -> FakeSession:
            return FakeSession()

        async def __aexit__(self, *_args: object) -> None:
            state["read"] += 1

    progress: list[tuple[int, int, str]] = []
    monkeypatch.setattr(
        storyboard_video_area,
        "AsyncSessionLocal",
        lambda: FakeSessionContext(),
    )
    monkeypatch.setattr(storyboard_video_area.asyncio, "sleep", lambda _seconds: _noop())

    jobs = await storyboard_video_area._wait_for_video_generation_jobs(
        [first_id, second_id],
        progress_callback=lambda done, total, detail: progress.append((done, total, detail)),
        poll_interval_seconds=0.1,
    )

    assert [job.status for job in jobs] == [
        GenerationJobStatus.SUCCEEDED,
        GenerationJobStatus.FAILED,
    ]
    assert progress[0][0:2] == (0, 2)
    assert progress[-1][0:2] == (2, 2)


@pytest.mark.asyncio
async def test_wait_for_video_jobs_reports_downloaded_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O pop-up informa as variantes já extraídas (o Vibes gera 4 opções/Shot)."""
    job_id = uuid4()
    reads = [
        {
            job_id: SimpleNamespace(
                id=job_id,
                status=GenerationJobStatus.RUNNING,
                progress=10,
                response_payload={"downloaded_variant_count": 2},
            ),
        },
        {
            job_id: SimpleNamespace(
                id=job_id,
                status=GenerationJobStatus.SUCCEEDED,
                progress=100,
                response_payload={"downloaded_variant_count": 4},
            ),
        },
    ]
    state = {"read": 0}

    class FakeSession:
        async def get(self, _model: type[GenerationJob], current_job_id: object) -> object:
            return reads[state["read"]][current_job_id]  # type: ignore[index]

    class FakeSessionContext:
        async def __aenter__(self) -> FakeSession:
            return FakeSession()

        async def __aexit__(self, *_args: object) -> None:
            state["read"] += 1

    progress: list[tuple[int, int, str]] = []
    monkeypatch.setattr(
        storyboard_video_area,
        "AsyncSessionLocal",
        lambda: FakeSessionContext(),
    )
    monkeypatch.setattr(storyboard_video_area.asyncio, "sleep", lambda _seconds: _noop())

    await storyboard_video_area._wait_for_video_generation_jobs(
        [job_id],
        progress_callback=lambda done, total, detail: progress.append((done, total, detail)),
        poll_interval_seconds=0.1,
    )

    running_detail = next(detail for done, _total, detail in progress if "opção" in detail)
    assert "2 opção(ões) já extraídas" in running_detail
    assert "4 opções de vídeo por Shot" in running_detail


async def _noop() -> None:
    return None
