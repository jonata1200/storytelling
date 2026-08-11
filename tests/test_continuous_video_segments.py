from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import GenerationJobStatus
from app.storytelling.models import Scene, Script, Shot
from app.video_generation import continuous
from app.video_generation.continuous import (
    build_continuous_video_segment_payloads,
    continuous_video_request_fingerprint,
    continuous_video_segment_idempotency_key,
    continuous_video_segment_needs_generation,
    continuous_video_segment_validation_errors,
    continuous_video_visual_context,
    create_or_get_continuous_video_segment,
    update_continuous_video_segment_prompt,
)
from app.video_generation.models import ContinuousVideoPlan, ContinuousVideoSegment
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
        "segment_number",
        "prompt",
        "duration_seconds",
        "generation_job_id",
        "asset_id",
        "source_segment_id",
        "source_video_asset_id",
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
    assert created.cost_estimate == Decimal("0.700000")
