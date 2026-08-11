from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.core.enums import GenerationJobStatus, GenerationJobType, ProjectStatus
from app.costs.service import estimate_operation_cost
from app.projects.models import Project
from app.providers.video.types import ProviderCapabilities, VideoRequest, VideoResult
from app.storytelling.models import Scene, Script, Shot
from app.video_generation import continuous
from app.video_generation.continuous import (
    CONTINUOUS_VIDEO_REVIEW_APPROVED,
    CONTINUOUS_VIDEO_REVIEW_PENDING,
    CONTINUOUS_VIDEO_REVIEW_READY,
    CONTINUOUS_VIDEO_REVIEW_REJECTED,
    approve_continuous_video_segment,
    build_continuous_video_segment_payloads,
    continuous_video_request_fingerprint,
    continuous_video_segment_continuity_summary,
    continuous_video_segment_idempotency_key,
    continuous_video_segment_is_approved,
    continuous_video_segment_needs_generation,
    continuous_video_segment_validation_errors,
    continuous_video_visual_context,
    create_or_get_continuous_video_segment,
    generate_continuous_video_segments,
    generate_next_continuous_video_segment,
    invalidate_continuous_video_downstream_segments,
    reject_continuous_video_segment,
    retry_failed_continuous_video_segment,
    update_continuous_video_segment_prompt,
)
from app.video_generation.models import (
    ContinuousVideoPlan,
    ContinuousVideoSegment,
    GenerationJob,
)
from app.video_generation.schemas import ContinuousVideoSegmentCreate
from app.visual_bible.models import Character, Location, Prop


def _script(project_id: UUID, *, duration: int, content: str) -> Script:
    return Script(
        id=uuid4(),
        project_id=project_id,
        artifact_id=uuid4(),
        story_idea_id=uuid4(),
        title="A Jornada de Clara",
        language="pt-BR",
        target_duration_seconds=duration,
        word_count=len(content.split()),
        content=content,
        updated_at=datetime.now(UTC),
    )


def _visual_context(project_id: UUID) -> dict:
    return continuous_video_visual_context(
        [
            Character(
                project_id=project_id,
                artifact_id=uuid4(),
                name="Clara",
                role="protagonista",
                canonical_profile={
                    "canonical_prompt": "Clara, jovem determinada, casaco vermelho, olhar atento"
                },
                character_fingerprint={},
            )
        ],
        [
            Location(
                project_id=project_id,
                artifact_id=uuid4(),
                name="Observatorio",
                description="Sala circular com telescopio antigo",
                canonical_profile={
                    "description": "observatorio antigo, luz azul da madrugada, metais polidos"
                },
            )
        ],
        [
            Prop(
                project_id=project_id,
                artifact_id=uuid4(),
                name="Relogio",
                narrative_importance="marca a contagem regressiva",
                canonical_profile={"description": "relogio de bolso dourado com riscos finos"},
            )
        ],
    )


def _planned_segment(project_id: UUID, number: int) -> ContinuousVideoSegment:
    prompt = (
        f"Segmento {number:02d} vertical cinematografico com Clara no observatorio, "
        "mantendo casaco vermelho, relogio dourado, luz azul, camera suave e acao "
        "continua sem cortes bruscos ou troca de identidade visual."
    )
    metadata = {
        "action": f"Clara executa a acao principal do segmento {number}.",
        "continuity": "continue diretamente o movimento anterior" if number > 1 else "inicio",
        "visual_context": _visual_context(project_id),
    }
    return ContinuousVideoSegment(
        id=uuid4(),
        project_id=project_id,
        segment_number=number,
        title=f"Segmento {number:02d}",
        prompt=prompt,
        duration_seconds=7,
        status=GenerationJobStatus.PENDING,
        provider="google_ai",
        model="veo-3.1-fast-generate-preview",
        request_fingerprint=f"{number}" * 64,
        idempotency_key=f"{number}" * 64,
        cost_estimate=Decimal("0.700000"),
        metadata_json=metadata,
    )


class _FakeProjectRepository:
    project: Project

    def __init__(self, _session: object) -> None:
        pass

    async def get_project(self, requested_project_id: UUID) -> Project | None:
        assert requested_project_id == self.project.id
        return self.project


class _FakeContinuousSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.flushed = 0

    def add(self, item: object) -> None:
        if getattr(item, "id", None) is None:
            item.id = uuid4()
        self.added.append(item)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _item: object) -> None:
        return None


class _FakeContinuousProvider:
    def __init__(self, tmp_path: Path, *, fail_operation: str | None = None) -> None:
        self.capabilities = ProviderCapabilities(text_to_video=True)
        self.tmp_path = tmp_path
        self.fail_operation = fail_operation
        self.submitted_prompts: list[str] = []
        self.polled_operations: list[str] = []

    async def submit_from_text(self, request: VideoRequest) -> str:
        self.submitted_prompts.append(request.prompt)
        return f"operations/continuous-{len(self.submitted_prompts)}"

    async def poll_submitted(
        self,
        request: VideoRequest,
        external_job_id: str,
    ) -> VideoResult:
        self.polled_operations.append(external_job_id)
        if external_job_id == self.fail_operation:
            raise RuntimeError("limite temporario do provider")
        path = self.tmp_path / f"{external_job_id.replace('/', '-')}.mp4"
        path.write_bytes(f"video-{external_job_id}".encode())
        return VideoResult(
            external_job_id=external_job_id,
            status=GenerationJobStatus.SUCCEEDED,
            file_path=path,
            storage_uri=path.as_posix(),
            sha256="a" * 64,
            provider="google_ai",
            model="veo-3.1-fast-generate-preview",
            metadata={"operation_name": external_job_id},
        )


async def _fake_continuous_generation_job(
    session: _FakeContinuousSession,
    segment: ContinuousVideoSegment,
    *,
    provider: str,
    model: str,
    operation: str,
    aspect_ratio: str,
    resolution: str,
    continuation_mode: str,
) -> GenerationJob:
    job = GenerationJob(
        id=uuid4(),
        project_id=segment.project_id,
        job_type=GenerationJobType.VIDEO,
        status=GenerationJobStatus.RUNNING,
        progress=5,
        attempts=1,
        max_attempts=3,
        provider=provider,
        model=model,
        idempotency_key=f"continuous-video:{segment.idempotency_key}",
        request_payload={
            "step": "continuous_video",
            "segment_id": str(segment.id),
            "operation": operation,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "continuation_mode": continuation_mode,
        },
        response_payload={},
        cost_estimate=segment.cost_estimate,
    )
    segment.generation_job_id = job.id
    session.add(job)
    return job


def _patch_continuous_generation_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project: Project,
    segments: list[ContinuousVideoSegment],
    provider: _FakeContinuousProvider,
    captured_budget: list[Decimal],
) -> None:
    _FakeProjectRepository.project = project
    plan = ContinuousVideoPlan(
        id=uuid4(),
        project_id=project.id,
        mode="continuous_fast",
        target_duration_seconds=sum(segment.duration_seconds for segment in segments),
        segment_duration_seconds=7,
        segment_count=len(segments),
        status="planned",
        metadata_json={},
    )

    async def fake_list_segments(
        _session: object,
        _project_id: UUID,
    ) -> list[ContinuousVideoSegment]:
        return segments

    async def fake_provider(
        _session: object,
        _project_id: UUID,
        _provider_name: str,
        _model: str | None,
    ) -> tuple[_FakeContinuousProvider, str, str, str, str]:
        return provider, "google_ai", "veo-3.1-fast-generate-preview", "9:16", "720p"

    async def fake_budget(
        _session: object,
        _project_id: UUID,
        estimated: Decimal,
        *,
        stage: str,
    ) -> None:
        assert stage == "continuous_video"
        captured_budget.append(estimated)

    async def fake_active_segment(_session: object, _project_id: UUID) -> None:
        return None

    async def fake_emit(*_args: object, **_kwargs: object) -> None:
        return None

    async def fake_plan(*_args: object, **_kwargs: object) -> ContinuousVideoPlan:
        return plan

    async def fake_assets_by_id(_session: object, _asset_ids: set[UUID]) -> dict[UUID, Asset]:
        return {}

    monkeypatch.setattr(continuous, "ProjectRepository", _FakeProjectRepository)
    monkeypatch.setattr(continuous, "list_continuous_video_segments", fake_list_segments)
    monkeypatch.setattr(continuous, "_continuous_video_provider_for_project", fake_provider)
    monkeypatch.setattr(continuous, "assert_project_budget_allows", fake_budget)
    monkeypatch.setattr(continuous, "_active_continuous_video_segment", fake_active_segment)
    monkeypatch.setattr(continuous, "_emit_continuous_video_segment_event", fake_emit)
    monkeypatch.setattr(continuous, "get_or_create_continuous_video_plan", fake_plan)
    monkeypatch.setattr(continuous, "advance_project_status", lambda *_args: None)
    monkeypatch.setattr(continuous, "_continuous_video_assets_by_id", fake_assets_by_id)
    monkeypatch.setattr(
        continuous,
        "_continuous_video_generation_job",
        _fake_continuous_generation_job,
    )


def test_continuous_video_metadata_defines_plan_and_segment_tables() -> None:
    plan_columns = set(ContinuousVideoPlan.__table__.columns.keys())
    segment_columns = set(ContinuousVideoSegment.__table__.columns.keys())

    assert {
        "project_id",
        "mode",
        "target_duration_seconds",
        "segment_duration_seconds",
        "segment_count",
        "status",
        "metadata_json",
    }.issubset(plan_columns)
    assert {
        "project_id",
        "script_id",
        "segment_number",
        "prompt",
        "duration_seconds",
        "generation_job_id",
        "asset_id",
        "generated_video_asset_id",
        "source_segment_id",
        "source_video_asset_id",
        "source_frame_asset_id",
        "final_frame_asset_id",
        "review_status",
        "external_operation_id",
        "request_fingerprint",
        "idempotency_key",
        "cost_estimate",
        "metadata_json",
    }.issubset(segment_columns)


def test_continuous_video_fingerprint_tracks_script_visual_and_previous_segment() -> None:
    project_id = uuid4()
    first = continuous_video_request_fingerprint(
        project_id=project_id,
        segment_number=2,
        prompt="Continue a caminhada pelo corredor.",
        duration_seconds=7,
        script_fingerprint="script-a",
        visual_fingerprint="visual-a",
        source_segment_id=uuid4(),
    )
    second = continuous_video_request_fingerprint(
        project_id=project_id,
        segment_number=2,
        prompt="Continue a caminhada pelo corredor.",
        duration_seconds=7,
        script_fingerprint="script-b",
        visual_fingerprint="visual-a",
        source_segment_id=uuid4(),
    )

    assert first != second
    assert len(first) == 64
    assert continuous_video_segment_idempotency_key(
        project_id,
        2,
        "google_ai",
        "veo-3.1-fast-generate-preview",
        first,
    ) != continuous_video_segment_idempotency_key(
        project_id,
        2,
        "google_ai",
        "veo-3.1-fast-generate-preview",
        second,
    )


def test_continuous_video_segment_generation_resume_rules() -> None:
    stale_running = ContinuousVideoSegment(
        project_id=uuid4(),
        segment_number=1,
        prompt="Segmento em processamento.",
        request_fingerprint="f" * 64,
        idempotency_key="k" * 64,
        status=GenerationJobStatus.RUNNING,
        updated_at=datetime.now(UTC) - timedelta(minutes=15),
    )
    fresh_failed = ContinuousVideoSegment(
        project_id=uuid4(),
        segment_number=2,
        prompt="Segmento com falha.",
        request_fingerprint="e" * 64,
        idempotency_key="j" * 64,
        status=GenerationJobStatus.FAILED,
        updated_at=datetime.now(UTC),
    )
    succeeded = ContinuousVideoSegment(
        project_id=uuid4(),
        segment_number=3,
        prompt="Segmento concluido.",
        request_fingerprint="d" * 64,
        idempotency_key="i" * 64,
        status=GenerationJobStatus.SUCCEEDED,
        updated_at=datetime.now(UTC),
    )

    assert continuous_video_segment_needs_generation(None) is True
    assert continuous_video_segment_needs_generation(stale_running) is True
    assert continuous_video_segment_needs_generation(fresh_failed) is False
    assert continuous_video_segment_needs_generation(fresh_failed, retry_failed=True) is True
    assert continuous_video_segment_needs_generation(succeeded, retry_failed=True) is False


def test_continuous_video_fast_cost_estimate_uses_text_to_video_override() -> None:
    estimate = estimate_operation_cost(
        "text_to_video",
        Decimal("7"),
        provider="google_ai",
        model="veo-3.1-fast-generate-preview",
    )

    assert estimate.unit == "second"
    assert estimate.unit_cost == Decimal("0.100000")
    assert estimate.estimated == Decimal("0.700000")


def test_continuous_video_planner_splits_short_script_without_scenes() -> None:
    project_id = uuid4()
    script = _script(
        project_id,
        duration=14,
        content=(
            "Clara entra no observatorio e encontra o relogio sobre a mesa.\n"
            "Ela percebe que a luz do telescopio aponta para uma estrela em queda."
        ),
    )

    payloads = build_continuous_video_segment_payloads(
        project_id=project_id,
        script=script,
        scenes=[],
        shots_by_scene={},
        visual_context=_visual_context(project_id),
        segment_duration_seconds=7,
    )

    assert len(payloads) == 2
    assert payloads[0].title == "Segmento 01"
    assert payloads[0].script_id == script.id
    assert payloads[0].review_status == CONTINUOUS_VIDEO_REVIEW_PENDING
    assert "Segmento 01" in payloads[0].prompt
    assert "Biblioteca Visual" in payloads[0].prompt
    assert "Nao criar legendas" in payloads[0].prompt
    assert payloads[0].metadata_json["characters"] == ["Clara"]
    assert payloads[0].metadata_json["locations"] == ["Observatorio"]
    assert payloads[0].metadata_json["props"] == ["Relogio"]
    assert payloads[1].metadata_json["previous_segment_fingerprint"]

    segment = ContinuousVideoSegment(
        project_id=project_id,
        segment_number=payloads[0].segment_number,
        prompt=payloads[0].prompt,
        duration_seconds=payloads[0].duration_seconds,
        request_fingerprint=payloads[0].request_fingerprint or "f" * 64,
        idempotency_key="k" * 64,
        metadata_json=payloads[0].metadata_json,
    )
    assert continuous_video_segment_validation_errors(segment) == []


def test_continuous_video_planner_groups_medium_script_shots() -> None:
    project_id = uuid4()
    script = _script(
        project_id,
        duration=14,
        content="Clara atravessa o observatorio enquanto o relogio pulsa.",
    )
    scene_id = uuid4()
    scene = Scene(
        id=scene_id,
        project_id=project_id,
        artifact_id=uuid4(),
        script_id=script.id,
        scene_number=1,
        title="Observatorio",
        summary="Clara descobre o sinal vindo do telescopio.",
        duration_seconds=13,
        payload={},
    )
    shots = [
        Shot(
            id=uuid4(),
            project_id=project_id,
            artifact_id=uuid4(),
            scene_id=scene_id,
            shot_number=1,
            duration_seconds=3,
            narration_text="",
            dialogue_text="",
            action="Clara entra no observatorio.",
            emotion="curiosidade",
            visual_composition="Plano medio com Clara e o telescopio.",
            camera_movement="travelling lento",
            generation_type="video",
            payload={},
        ),
        Shot(
            id=uuid4(),
            project_id=project_id,
            artifact_id=uuid4(),
            scene_id=scene_id,
            shot_number=2,
            duration_seconds=4,
            narration_text="",
            dialogue_text="",
            action="Clara pega o relogio na mesa.",
            emotion="tensao",
            visual_composition="Close no relogio dourado.",
            camera_movement="aproximacao suave",
            generation_type="video",
            payload={},
        ),
        Shot(
            id=uuid4(),
            project_id=project_id,
            artifact_id=uuid4(),
            scene_id=scene_id,
            shot_number=3,
            duration_seconds=6,
            narration_text="",
            dialogue_text="",
            action="O telescopio projeta a estrela em queda.",
            emotion="assombro",
            visual_composition="Luz azul atravessa a sala.",
            camera_movement="panoramica curta",
            generation_type="video",
            payload={},
        ),
    ]

    payloads = build_continuous_video_segment_payloads(
        project_id=project_id,
        script=script,
        scenes=[scene],
        shots_by_scene={scene_id: shots},
        visual_context=_visual_context(project_id),
        segment_duration_seconds=7,
    )

    assert len(payloads) == 2
    assert payloads[0].metadata_json["source_shot_numbers"] == [1, 2]
    assert payloads[1].metadata_json["source_shot_numbers"] == [3]
    assert "continue diretamente" in payloads[1].metadata_json["continuity"]


def test_continuous_video_planner_handles_long_script_chunks() -> None:
    project_id = uuid4()
    content = "\n".join(
        f"Momento {index}: Clara segue a pista luminosa no observatorio."
        for index in range(1, 11)
    )
    script = _script(project_id, duration=35, content=content)

    payloads = build_continuous_video_segment_payloads(
        project_id=project_id,
        script=script,
        scenes=[],
        shots_by_scene={},
        visual_context=_visual_context(project_id),
        segment_duration_seconds=7,
    )

    assert len(payloads) == 5
    assert payloads[0].metadata_json["source_text"].startswith("Momento 1")
    assert payloads[-1].metadata_json["source_text"].startswith("Momento 9")
    assert len({payload.request_fingerprint for payload in payloads}) == 5


def test_continuous_video_segment_validation_rejects_generic_prompt() -> None:
    segment = ContinuousVideoSegment(
        project_id=uuid4(),
        segment_number=1,
        prompt="Curto demais.",
        duration_seconds=7,
        request_fingerprint="f" * 64,
        idempotency_key="k" * 64,
        metadata_json={},
    )

    errors = continuous_video_segment_validation_errors(segment)

    assert "prompt generico demais" in errors
    assert "Biblioteca Visual ausente" in errors


@pytest.mark.asyncio
async def test_update_continuous_video_segment_prompt_recomputes_fingerprint() -> None:
    project_id = uuid4()
    segment = ContinuousVideoSegment(
        id=uuid4(),
        project_id=project_id,
        segment_number=1,
        title="Segmento 01",
        prompt="Prompt original com detalhes suficientes para passar pela validacao.",
        duration_seconds=7,
        status=GenerationJobStatus.PENDING,
        provider="google_ai",
        model="veo-3.1-fast-generate-preview",
        request_fingerprint="f" * 64,
        idempotency_key="k" * 64,
        metadata_json={
            "action": "Clara observa o relogio",
            "continuity": "inicio",
            "visual_context": _visual_context(project_id),
        },
    )

    class FakeSession:
        def __init__(self, item: ContinuousVideoSegment) -> None:
            self.item = item
            self.flushed = 0

        async def get(self, _model: object, item_id: object) -> ContinuousVideoSegment | None:
            assert item_id == segment.id
            return self.item

        async def flush(self) -> None:
            self.flushed += 1

    new_prompt = (
        "Segmento vertical realista com Clara no observatorio, mantendo casaco vermelho, "
        "luz azul, relogio dourado na mao e movimento continuo de camera ate o telescopio."
    )
    fake_session = FakeSession(segment)

    updated = await update_continuous_video_segment_prompt(
        cast(AsyncSession, fake_session),
        project_id,
        segment.id,
        prompt=new_prompt,
        title="Ajuste visual",
    )

    assert updated is segment
    assert segment.title == "Ajuste visual"
    assert segment.prompt == new_prompt
    assert segment.metadata_json["custom_prompt"] is True
    assert segment.request_fingerprint != "f" * 64
    assert segment.idempotency_key != "k" * 64
    assert fake_session.flushed == 1


@pytest.mark.asyncio
async def test_generate_continuous_video_segments_stops_at_review_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    project = Project(id=project_id, title="Projeto", status=ProjectStatus.PRODUCTION_PLANNING)
    segments = [_planned_segment(project_id, 1), _planned_segment(project_id, 2)]
    provider = _FakeContinuousProvider(tmp_path)
    captured_budget: list[Decimal] = []
    _patch_continuous_generation_dependencies(
        monkeypatch,
        project=project,
        segments=segments,
        provider=provider,
        captured_budget=captured_budget,
    )
    session = _FakeContinuousSession()

    jobs, processed = await generate_continuous_video_segments(
        cast(AsyncSession, session),
        project_id,
    )

    assert [segment.segment_number for segment in processed] == [1]
    assert [job.request_payload["step"] for job in jobs] == ["continuous_video"]
    assert provider.submitted_prompts == [segments[0].prompt]
    assert provider.polled_operations == ["operations/continuous-1"]
    assert segments[0].status == GenerationJobStatus.SUCCEEDED
    assert segments[0].review_status == CONTINUOUS_VIDEO_REVIEW_READY
    assert segments[1].status == GenerationJobStatus.PENDING
    assert segments[0].asset_id is not None
    assert segments[1].source_segment_id is None
    assert segments[1].source_video_asset_id is None
    assert len([item for item in session.added if isinstance(item, Asset)]) == 1
    assert captured_budget == [Decimal("0.700000")]


@pytest.mark.asyncio
async def test_generate_continuous_video_segments_can_generate_partial_queue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    project = Project(id=project_id, title="Projeto", status=ProjectStatus.PRODUCTION_PLANNING)
    segments = [_planned_segment(project_id, 1), _planned_segment(project_id, 2)]
    provider = _FakeContinuousProvider(tmp_path)
    captured_budget: list[Decimal] = []
    _patch_continuous_generation_dependencies(
        monkeypatch,
        project=project,
        segments=segments,
        provider=provider,
        captured_budget=captured_budget,
    )

    jobs, processed = await generate_continuous_video_segments(
        cast(AsyncSession, _FakeContinuousSession()),
        project_id,
        max_segments=1,
    )

    assert [segment.segment_number for segment in processed] == [1]
    assert len(jobs) == 1
    assert provider.submitted_prompts == [segments[0].prompt]
    assert segments[0].status == GenerationJobStatus.SUCCEEDED
    assert segments[1].status == GenerationJobStatus.PENDING
    assert captured_budget == [Decimal("0.700000")]


@pytest.mark.asyncio
async def test_generate_continuous_video_segments_stops_on_middle_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    project = Project(id=project_id, title="Projeto", status=ProjectStatus.PRODUCTION_PLANNING)
    first = _planned_segment(project_id, 1)
    first.status = GenerationJobStatus.SUCCEEDED
    first.review_status = CONTINUOUS_VIDEO_REVIEW_APPROVED
    first.asset_id = uuid4()
    segments = [first, _planned_segment(project_id, 2), _planned_segment(project_id, 3)]
    provider = _FakeContinuousProvider(tmp_path, fail_operation="operations/continuous-1")
    captured_budget: list[Decimal] = []
    _patch_continuous_generation_dependencies(
        monkeypatch,
        project=project,
        segments=segments,
        provider=provider,
        captured_budget=captured_budget,
    )

    _jobs, processed = await generate_continuous_video_segments(
        cast(AsyncSession, _FakeContinuousSession()),
        project_id,
    )

    assert [segment.segment_number for segment in processed] == [1, 2]
    assert provider.submitted_prompts == [segments[1].prompt]
    assert segments[0].status == GenerationJobStatus.SUCCEEDED
    assert segments[1].status == GenerationJobStatus.FAILED
    assert segments[1].metadata_json["error"] == "limite temporario do provider"
    assert segments[2].status == GenerationJobStatus.PENDING
    assert captured_budget == [Decimal("0.700000")]


@pytest.mark.asyncio
async def test_generate_continuous_video_segments_resumes_without_resubmitting_ready_segments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    project = Project(id=project_id, title="Projeto", status=ProjectStatus.PRODUCTION_PLANNING)
    first = _planned_segment(project_id, 1)
    first.status = GenerationJobStatus.SUCCEEDED
    first.review_status = CONTINUOUS_VIDEO_REVIEW_APPROVED
    first.asset_id = uuid4()
    second = _planned_segment(project_id, 2)
    second.status = GenerationJobStatus.RUNNING
    second.external_operation_id = "operations/resume-2"
    second.updated_at = datetime.now(UTC) - timedelta(minutes=30)
    segments = [first, second]
    provider = _FakeContinuousProvider(tmp_path)
    captured_budget: list[Decimal] = []
    _patch_continuous_generation_dependencies(
        monkeypatch,
        project=project,
        segments=segments,
        provider=provider,
        captured_budget=captured_budget,
    )

    jobs, processed = await generate_continuous_video_segments(
        cast(AsyncSession, _FakeContinuousSession()),
        project_id,
    )

    assert [segment.segment_number for segment in processed] == [1, 2]
    assert len(jobs) == 1
    assert provider.submitted_prompts == []
    assert provider.polled_operations == ["operations/resume-2"]
    assert second.status == GenerationJobStatus.SUCCEEDED
    assert second.source_video_asset_id == first.asset_id
    assert captured_budget == [Decimal("0.000000")]


@pytest.mark.asyncio
async def test_generate_continuous_video_segments_retries_failed_and_continues(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    project = Project(id=project_id, title="Projeto", status=ProjectStatus.PRODUCTION_PLANNING)
    first = _planned_segment(project_id, 1)
    first.status = GenerationJobStatus.SUCCEEDED
    first.review_status = CONTINUOUS_VIDEO_REVIEW_APPROVED
    first.asset_id = uuid4()
    second = _planned_segment(project_id, 2)
    second.status = GenerationJobStatus.FAILED
    second.metadata_json = {**(second.metadata_json or {}), "error": "limite anterior"}
    third = _planned_segment(project_id, 3)
    segments = [first, second, third]
    provider = _FakeContinuousProvider(tmp_path)
    captured_budget: list[Decimal] = []
    _patch_continuous_generation_dependencies(
        monkeypatch,
        project=project,
        segments=segments,
        provider=provider,
        captured_budget=captured_budget,
    )

    jobs, processed = await generate_continuous_video_segments(
        cast(AsyncSession, _FakeContinuousSession()),
        project_id,
        retry_failed=True,
    )

    assert [segment.segment_number for segment in processed] == [1, 2]
    assert len(jobs) == 1
    assert provider.submitted_prompts == [second.prompt]
    assert second.status == GenerationJobStatus.SUCCEEDED
    assert second.review_status == CONTINUOUS_VIDEO_REVIEW_READY
    assert third.status == GenerationJobStatus.PENDING
    assert second.source_video_asset_id == first.asset_id
    assert third.source_video_asset_id is None
    assert captured_budget == [Decimal("0.700000")]


@pytest.mark.asyncio
async def test_create_continuous_video_segment_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()

    class FakeRepository:
        def __init__(self, _session: object) -> None:
            pass

        async def get_project(self, requested_project_id: object) -> object | None:
            assert requested_project_id == project_id
            return object()

    class FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.flushed = 0

        def add(self, item: object) -> None:
            self.added.append(item)

        async def flush(self) -> None:
            self.flushed += 1

    fake_session = FakeSession()
    existing_by_key: dict[str, ContinuousVideoSegment] = {}

    async def fake_get_by_key(_session: object, key: str) -> ContinuousVideoSegment | None:
        return existing_by_key.get(key)

    monkeypatch.setattr(continuous, "ProjectRepository", FakeRepository)
    monkeypatch.setattr(
        continuous,
        "get_continuous_video_segment_by_idempotency_key",
        fake_get_by_key,
    )

    payload = ContinuousVideoSegmentCreate(
        segment_number=1,
        title="Abertura",
        prompt="Clara abre a porta e observa a sala iluminada.",
        duration_seconds=7,
    )

    created = await create_or_get_continuous_video_segment(
        cast(AsyncSession, fake_session),
        project_id,
        payload,
    )
    existing_by_key[created.idempotency_key] = created
    repeated = await create_or_get_continuous_video_segment(
        cast(AsyncSession, fake_session),
        project_id,
        payload,
    )

    assert repeated is created
    assert fake_session.added == [created]
    assert fake_session.flushed == 1
    assert created.provider == "google_ai"
    assert created.model == "veo-3.1-fast-generate-preview"
    assert created.status == GenerationJobStatus.PENDING
    assert created.review_status == CONTINUOUS_VIDEO_REVIEW_PENDING
    assert created.cost_estimate == Decimal("0.700000")


@pytest.mark.asyncio
async def test_continuous_video_success_enters_review_and_stores_final_frame(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    project = Project(id=project_id, title="Projeto", status=ProjectStatus.PRODUCTION_PLANNING)
    segments = [_planned_segment(project_id, 1)]
    provider = _FakeContinuousProvider(tmp_path)
    captured_budget: list[Decimal] = []
    _patch_continuous_generation_dependencies(
        monkeypatch,
        project=project,
        segments=segments,
        provider=provider,
        captured_budget=captured_budget,
    )

    def fake_extract(_video_asset: Asset, *, segment_number: int) -> tuple[Path | None, str | None]:
        path = tmp_path / f"segment-{segment_number}-final.jpg"
        path.write_bytes(b"final-frame")
        return path, None

    monkeypatch.setattr(continuous, "_extract_continuous_video_final_frame", fake_extract)
    session = _FakeContinuousSession()

    _jobs, processed = await generate_continuous_video_segments(
        cast(AsyncSession, session),
        project_id,
    )

    segment = processed[0]
    assert segment.status == GenerationJobStatus.SUCCEEDED
    assert segment.review_status == CONTINUOUS_VIDEO_REVIEW_READY
    assert segment.generated_video_asset_id == segment.asset_id
    assert segment.final_frame_asset_id is not None
    assert segment.metadata_json["final_frame_asset_id"] == str(segment.final_frame_asset_id)
    assert len([item for item in session.added if isinstance(item, Asset)]) == 2


@pytest.mark.asyncio
async def test_generate_next_continuous_video_segment_waits_for_review_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    first = _planned_segment(project_id, 1)
    first.status = GenerationJobStatus.SUCCEEDED
    first.asset_id = uuid4()
    first.review_status = CONTINUOUS_VIDEO_REVIEW_READY
    second = _planned_segment(project_id, 2)

    async def fake_list_segments(
        _session: object,
        _project_id: UUID,
    ) -> list[ContinuousVideoSegment]:
        return [first, second]

    monkeypatch.setattr(continuous, "list_continuous_video_segments", fake_list_segments)

    with pytest.raises(ValueError, match="Revise e aprove"):
        await generate_next_continuous_video_segment(
            cast(AsyncSession, _FakeContinuousSession()),
            project_id,
        )

    first.review_status = CONTINUOUS_VIDEO_REVIEW_APPROVED
    assert continuous_video_segment_is_approved(first) is True


@pytest.mark.asyncio
async def test_approve_continuous_video_segment_links_next_continuity_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    first = _planned_segment(project_id, 1)
    first.status = GenerationJobStatus.SUCCEEDED
    first.asset_id = uuid4()
    first.generated_video_asset_id = first.asset_id
    first.final_frame_asset_id = uuid4()
    first.review_status = CONTINUOUS_VIDEO_REVIEW_READY
    first.metadata_json = {
        **(first.metadata_json or {}),
        "action": "Clara abre a porta com cuidado.",
        "final_frame_storage_uri": "storage/final.jpg",
    }
    second = _planned_segment(project_id, 2)
    segments = [first, second]

    class FakeSession:
        async def get(self, _model: object, item_id: object) -> ContinuousVideoSegment | None:
            return next((segment for segment in segments if segment.id == item_id), None)

        async def flush(self) -> None:
            return None

    async def fake_get_by_number(
        _session: object,
        _project_id: UUID,
        number: int,
    ) -> ContinuousVideoSegment | None:
        return next((segment for segment in segments if segment.segment_number == number), None)

    monkeypatch.setattr(
        continuous,
        "get_continuous_video_segment_by_number",
        fake_get_by_number,
    )

    approved = await approve_continuous_video_segment(
        cast(AsyncSession, FakeSession()),
        project_id,
        first.id,
        note="bom corte",
    )

    assert approved is first
    assert first.review_status == CONTINUOUS_VIDEO_REVIEW_APPROVED
    assert first.metadata_json["review_decision"] == CONTINUOUS_VIDEO_REVIEW_APPROVED
    assert first.metadata_json["review_previous_status"] == CONTINUOUS_VIDEO_REVIEW_READY
    assert first.metadata_json["review_note"] == "bom corte"
    assert continuous_video_segment_continuity_summary(first).startswith("Segmento 01")
    assert second.source_segment_id == first.id
    assert second.source_video_asset_id == first.asset_id
    assert second.source_frame_asset_id == first.final_frame_asset_id
    assert second.metadata_json["continuity_source_summary"] == first.metadata_json[
        "continuity_summary"
    ]


@pytest.mark.asyncio
async def test_reject_continuous_video_segment_blocks_downstream_continuity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    first = _planned_segment(project_id, 1)
    first.status = GenerationJobStatus.SUCCEEDED
    first.asset_id = uuid4()
    first.review_status = CONTINUOUS_VIDEO_REVIEW_READY
    second = _planned_segment(project_id, 2)
    second.source_segment_id = first.id
    second.source_video_asset_id = first.asset_id
    second.source_frame_asset_id = uuid4()
    segments = [first, second]

    class FakeSession:
        async def get(self, _model: object, item_id: object) -> ContinuousVideoSegment | None:
            return next((segment for segment in segments if segment.id == item_id), None)

        async def flush(self) -> None:
            return None

    async def fake_list_segments(
        _session: object,
        _project_id: UUID,
    ) -> list[ContinuousVideoSegment]:
        return segments

    monkeypatch.setattr(continuous, "list_continuous_video_segments", fake_list_segments)

    rejected = await reject_continuous_video_segment(
        cast(AsyncSession, FakeSession()),
        project_id,
        first.id,
        note="trocar enquadramento",
    )

    assert rejected is first
    assert first.review_status == CONTINUOUS_VIDEO_REVIEW_REJECTED
    assert first.metadata_json["review_decision"] == CONTINUOUS_VIDEO_REVIEW_REJECTED
    assert first.metadata_json["review_note"] == "trocar enquadramento"
    assert second.status == GenerationJobStatus.PENDING
    assert second.source_segment_id is None
    assert second.source_video_asset_id is None
    assert second.source_frame_asset_id is None


@pytest.mark.asyncio
async def test_retry_failed_continuous_video_segment_requires_failed_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    failed = _planned_segment(project_id, 1)
    failed.status = GenerationJobStatus.FAILED
    calls: list[dict[str, object]] = []

    class FakeSession:
        async def get(self, _model: object, item_id: object) -> ContinuousVideoSegment | None:
            return failed if item_id == failed.id else None

    async def fake_generate_segment(
        _session: object,
        _project_id: UUID,
        segment_id: UUID,
        **kwargs: object,
    ) -> tuple[list[GenerationJob], list[ContinuousVideoSegment]]:
        calls.append({"segment_id": segment_id, **kwargs})
        return [], [failed]

    monkeypatch.setattr(
        continuous,
        "generate_continuous_video_segment",
        fake_generate_segment,
    )

    _jobs, processed = await retry_failed_continuous_video_segment(
        cast(AsyncSession, FakeSession()),
        project_id,
        failed.id,
    )

    assert processed == [failed]
    assert calls[0]["segment_id"] == failed.id
    assert calls[0]["retry_failed"] is True


@pytest.mark.asyncio
async def test_downstream_invalidation_keeps_approved_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    first = _planned_segment(project_id, 1)
    first.status = GenerationJobStatus.SUCCEEDED
    first.review_status = CONTINUOUS_VIDEO_REVIEW_APPROVED
    second = _planned_segment(project_id, 2)
    second.status = GenerationJobStatus.SUCCEEDED
    second.review_status = CONTINUOUS_VIDEO_REVIEW_READY
    second.asset_id = uuid4()
    second.final_frame_asset_id = uuid4()
    third = _planned_segment(project_id, 3)
    third.status = GenerationJobStatus.SUCCEEDED
    third.review_status = CONTINUOUS_VIDEO_REVIEW_APPROVED
    third.asset_id = uuid4()
    segments = [first, second, third]

    async def fake_list_segments(
        _session: object,
        _project_id: UUID,
    ) -> list[ContinuousVideoSegment]:
        return segments

    monkeypatch.setattr(continuous, "list_continuous_video_segments", fake_list_segments)
    session = _FakeContinuousSession()

    invalidated = await invalidate_continuous_video_downstream_segments(
        cast(AsyncSession, session),
        project_id,
        1,
    )

    assert invalidated == [second]
    assert second.status == GenerationJobStatus.PENDING
    assert second.review_status == CONTINUOUS_VIDEO_REVIEW_PENDING
    assert second.asset_id is None
    assert second.final_frame_asset_id is None
    assert third.status == GenerationJobStatus.SUCCEEDED
    assert third.review_status == CONTINUOUS_VIDEO_REVIEW_APPROVED
    assert session.flushed == 1
