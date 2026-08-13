"""Testes da etapa de produção de vídeo como assistente do Google Flow.

A geração de vídeo por IA foi removida: o pipeline agora planeja segmentos e
prepara um pacote (prompt + frame inicial + frame final) para o usuário criar
o vídeo manualmente no Google Flow. Estes testes cobrem o planejamento, a
validação, a edição de prompt, a conclusão manual (done), a rejeição (refazer)
e a invalidação downstream.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.core.enums import GenerationJobStatus, ProjectStatus
from app.projects.models import Project
from app.storytelling.models import Scene, Script, Shot
from app.video_generation import continuous
from app.video_generation.continuous import (
    CONTINUOUS_VIDEO_REVIEW_DONE,
    CONTINUOUS_VIDEO_REVIEW_PENDING,
    CONTINUOUS_VIDEO_REVIEW_READY,
    CONTINUOUS_VIDEO_REVIEW_REJECTED,
    approve_continuous_video_segment,
    build_continuous_video_segment_payloads,
    continuous_video_request_fingerprint,
    continuous_video_segment_continuity_summary,
    continuous_video_segment_idempotency_key,
    continuous_video_segment_is_approved,
    continuous_video_segment_validation_errors,
    continuous_video_visual_context,
    create_or_get_continuous_video_segment,
    invalidate_continuous_video_downstream_segments,
    prepare_continuous_video_flow_package,
    reject_continuous_video_segment,
    update_continuous_video_segment_prompt,
)
from app.video_generation.models import (
    ContinuousVideoPlan,
    ContinuousVideoSegment,
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
        provider="flow_assistant",
        model="google_flow",
        request_fingerprint=f"{number}" * 64,
        idempotency_key=f"{number}" * 64,
        cost_estimate=Decimal("0.000000"),
        metadata_json=metadata,
    )


class _FakeContinuousSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.flushed = 0

    def add(self, item: Any) -> None:
        if getattr(item, "id", None) is None:
            item.id = uuid4()
        self.added.append(item)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _item: object) -> None:
        return None


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
        "flow_assistant",
        "google_flow",
        first,
    ) != continuous_video_segment_idempotency_key(
        project_id,
        2,
        "flow_assistant",
        "google_flow",
        second,
    )


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
    assert "Plano unico vertical 9:16" in payloads[0].prompt
    assert "Acao" in payloads[0].prompt
    assert "Nao criar legendas" in payloads[0].prompt
    assert "first frame" in payloads[0].prompt
    assert "last frame" in payloads[0].prompt
    assert "flow.google.com" in payloads[0].prompt
    assert payloads[0].metadata_json["action"].endswith(".")
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


def test_continuous_video_planner_does_not_create_marker_only_first_segment() -> None:
    project_id = uuid4()
    script = _script(
        project_id,
        duration=120,
        content=(
            "FADE IN:\n\n"
            "CENA 1\n"
            "INT. QUARTO - DIA\n\n"
            "Elias pesa um frasco de perfume vazio em uma balanca digital, "
            "anota o numero em um caderno antigo e prende a respiracao.\n\n"
            "CENA 2\n"
            "INT. QUARTO - DIA\n\n"
            "Elias coloca uma alianca dourada no centro da balanca, percebe "
            "um peso impossivel e encara o quarto vazio em silencio.\n\n"
            "FADE OUT."
        ),
    )

    payloads = build_continuous_video_segment_payloads(
        project_id=project_id,
        script=script,
        scenes=[],
        shots_by_scene={},
        visual_context=_visual_context(project_id),
    )

    first_source = payloads[0].metadata_json["source_text"]
    assert first_source != "FADE IN:\nCENA 1"
    assert "Elias pesa" in first_source
    assert "FADE OUT" not in payloads[-1].metadata_json["source_text"]


def test_continuous_video_planner_preserves_sentence_boundaries_in_fallback_chunks() -> None:
    project_id = uuid4()
    script = _script(
        project_id,
        duration=40,
        content=(
            "O apartamento e vasto, minimalista e imerso em um silencio opressor. "
            "Arthur, 65 anos, veste um fraque impecavel, mas seus olhos carregam "
            "a exaustao de quem luta contra o invisivel. "
            "Ele segura uma batuta com forca diante do vazio. "
            "Arthur comeca a reger uma orquestra ausente."
        ),
    )

    payloads = build_continuous_video_segment_payloads(
        project_id=project_id,
        script=script,
        scenes=[],
        shots_by_scene={},
        visual_context=_visual_context(project_id),
        segment_duration_seconds=8,
    )

    assert payloads[0].metadata_json["source_text"].endswith("opressor.")
    assert "exaustao de." not in payloads[0].prompt
    assert "quem luta contra o invisivel." in payloads[1].metadata_json["source_text"]
    assert "Converta ideias internas em sinais visiveis" in payloads[0].prompt


def test_continuous_video_segment_validation_rejects_incomplete_action() -> None:
    project_id = uuid4()
    segment = ContinuousVideoSegment(
        project_id=project_id,
        segment_number=1,
        prompt=(
            "Prompt para Google Flow - Segmento 01\n\n"
            "ACAO VISIVEL DO SEGMENTO\n"
            "Arthur carrega a exaustao de.\n\n"
            "Biblioteca Visual canonica\n"
            "Personagens: Arthur."
        ),
        duration_seconds=8,
        request_fingerprint="f" * 64,
        idempotency_key="k" * 64,
        metadata_json={
            "action": "Arthur carrega a exaustao de.",
            "continuity": "inicio",
            "visual_context": _visual_context(project_id),
        },
    )

    errors = continuous_video_segment_validation_errors(segment)

    assert "acao principal termina em frase incompleta" in errors
    assert "prompt contem frase incompleta" in errors


def test_continuous_video_segment_prompt_uses_compact_visual_context() -> None:
    project_id = uuid4()
    visual_context = continuous_video_visual_context(
        [
            Character(
                project_id=project_id,
                artifact_id=uuid4(),
                name="Clara",
                role="protagonista",
                canonical_profile={"canonical_prompt": "Clara " + "detalhe visual " * 80},
                character_fingerprint={},
            )
        ],
        [],
        [],
    )

    payload = build_continuous_video_segment_payloads(
        project_id=project_id,
        script=_script(project_id, duration=8, content="Clara observa a porta."),
        scenes=[],
        shots_by_scene={},
        visual_context=visual_context,
    )[0]

    assert len(payload.prompt) < 1200
    assert "detalhe visual " * 20 not in payload.prompt


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
async def test_update_continuous_video_segment_prompt_recomputes_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    segment = ContinuousVideoSegment(
        id=uuid4(),
        project_id=project_id,
        segment_number=1,
        title="Segmento 01",
        prompt="Prompt original com detalhes suficientes para passar pela validacao.",
        duration_seconds=7,
        status=GenerationJobStatus.PENDING,
        provider="flow_assistant",
        model="google_flow",
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

    async def fake_list_segments(
        _session: object,
        _project_id: UUID,
    ) -> list[ContinuousVideoSegment]:
        return [segment]

    monkeypatch.setattr(continuous, "list_continuous_video_segments", fake_list_segments)

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
    assert fake_session.flushed == 2


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
    assert created.provider == "flow_assistant"
    assert created.model == "google_flow"
    assert created.status == GenerationJobStatus.PENDING
    assert created.review_status == CONTINUOUS_VIDEO_REVIEW_PENDING


@pytest.mark.asyncio
async def test_approve_continuous_video_segment_marks_done_and_links_next_continuity_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    first = _planned_segment(project_id, 1)
    first.status = GenerationJobStatus.SUCCEEDED
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

    async def fake_list_segments(
        _session: object,
        _project_id: UUID,
    ) -> list[ContinuousVideoSegment]:
        return segments

    async def fake_emit(*_args: object, **_kwargs: object) -> None:
        return None

    async def fake_get_project(_session: object, _project_id: UUID) -> object | None:
        return object()

    async def fake_get_plan(
        _session: object,
        _project_id: UUID,
        _payload: object = None,
    ) -> ContinuousVideoPlan:
        return ContinuousVideoPlan(project_id=_project_id)

    monkeypatch.setattr(
        continuous,
        "get_continuous_video_segment_by_number",
        fake_get_by_number,
    )
    monkeypatch.setattr(continuous, "list_continuous_video_segments", fake_list_segments)
    monkeypatch.setattr(continuous, "_emit_continuous_video_segment_event", fake_emit)
    monkeypatch.setattr(continuous, "ProjectRepository", type(
        "FakeRepo",
        (),
        {"__init__": lambda self, _s: None, "get_project": fake_get_project},
    ))
    monkeypatch.setattr(continuous, "get_or_create_continuous_video_plan", fake_get_plan)
    monkeypatch.setattr(continuous, "advance_project_status", lambda *_args: None)

    approved = await approve_continuous_video_segment(
        cast(AsyncSession, FakeSession()),
        project_id,
        first.id,
        note="bom corte",
    )

    assert approved is first
    assert first.review_status == CONTINUOUS_VIDEO_REVIEW_DONE
    assert continuous_video_segment_is_approved(first) is True
    assert first.metadata_json["review_decision"] == CONTINUOUS_VIDEO_REVIEW_DONE
    assert first.metadata_json["review_previous_status"] == CONTINUOUS_VIDEO_REVIEW_READY
    assert first.metadata_json["review_note"] == "bom corte"
    assert continuous_video_segment_continuity_summary(first).startswith("Segmento 01")
    assert second.source_segment_id == first.id
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
    first.review_status = CONTINUOUS_VIDEO_REVIEW_READY
    second = _planned_segment(project_id, 2)
    second.source_segment_id = first.id
    second.source_video_asset_id = uuid4()
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
async def test_downstream_invalidation_keeps_done_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    first = _planned_segment(project_id, 1)
    first.status = GenerationJobStatus.SUCCEEDED
    first.review_status = CONTINUOUS_VIDEO_REVIEW_DONE
    second = _planned_segment(project_id, 2)
    second.status = GenerationJobStatus.SUCCEEDED
    second.review_status = CONTINUOUS_VIDEO_REVIEW_READY
    second.final_frame_asset_id = uuid4()
    third = _planned_segment(project_id, 3)
    third.status = GenerationJobStatus.SUCCEEDED
    third.review_status = CONTINUOUS_VIDEO_REVIEW_DONE
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
    assert second.final_frame_asset_id is None
    assert third.status == GenerationJobStatus.SUCCEEDED
    assert third.review_status == CONTINUOUS_VIDEO_REVIEW_DONE
    assert session.flushed == 1


@pytest.mark.asyncio
async def test_prepare_continuous_video_flow_package_generates_final_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preparar o pacote gera o frame final (imagem) e grava final_frame_asset_id."""
    project_id = uuid4()
    segment = _planned_segment(project_id, 1)
    segment.source_frame_asset_id = uuid4()
    segment.metadata_json = {
        **(segment.metadata_json or {}),
        "initial_frame_asset_id": str(segment.source_frame_asset_id),
    }

    class FakeRepository:
        def __init__(self, _session: object) -> None:
            pass

        async def get_project(self, _requested_project_id: UUID) -> Project:
            return Project(id=project_id, title="Projeto", status=ProjectStatus.PRODUCTION_PLANNING)

    class FakeSession:
        def __init__(self, item: ContinuousVideoSegment) -> None:
            self.item = item
            self.added: list[object] = []
            self.commits = 0

        async def execute(self, _statement: object) -> object:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: self.item))

        async def get(
            self,
            _model: object,
            asset_id: UUID,
        ) -> Asset | None:
            return (
                Asset(
                    id=asset_id,
                    project_id=project_id,
                    kind="image",
                    storage_uri="storage/frames/initial.jpg",
                    content_type="image/jpeg",
                    sha256="c" * 64,
                )
                if asset_id == segment.source_frame_asset_id
                else None
            )

        def add(self, item: Any) -> None:
            if getattr(item, "id", None) is None:
                item.id = uuid4()
            self.added.append(item)

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            self.commits += 1

        async def refresh(self, _item: object) -> None:
            return None

    session = FakeSession(segment)

    async def fake_list_segments(
        _session: object,
        _project_id: UUID,
    ) -> list[ContinuousVideoSegment]:
        return [segment]

    class FakeImageProvider:
        provider_name = "google_ai"

    async def fake_image_provider(
        _session: object,
        _project_id: UUID,
    ) -> tuple[FakeImageProvider, str, str]:
        return FakeImageProvider(), "gemini-3.1-flash-lite-image", "images"

    class FakeImage:
        storage_uri = "storage/frames/final.jpg"
        content_type = "image/jpeg"
        sha256 = "b" * 64
        provider = "google_ai"
        model = "gemini-3.1-flash-lite-image"
        estimated_cost = Decimal("0.000000")

    async def fake_generate_image(
        _provider: object,
        _request: object,
    ) -> tuple[FakeImage, dict]:
        return FakeImage(), {}

    async def fake_emit(*_args: object, **_kwargs: object) -> None:
        return None

    async def fake_budget(
        _session: object,
        _project_id: UUID,
        estimated: Decimal,
        *,
        stage: str,
    ) -> None:
        assert stage == "continuous_video_flow"
        assert estimated >= Decimal("0.000000")

    def fake_settings() -> object:
        return SimpleNamespace(local_storage_path=Path("storage"))

    async def fake_production_settings(
        _session: object,
        _project_id: UUID,
    ) -> object:
        return SimpleNamespace(
            aspect_ratio="9:16",
            image_resolution="1K",
            metadata_json={},
        )

    monkeypatch.setattr(continuous, "ProjectRepository", FakeRepository)
    monkeypatch.setattr(continuous, "list_continuous_video_segments", fake_list_segments)
    monkeypatch.setattr(continuous, "_image_provider_for_project", fake_image_provider)
    monkeypatch.setattr(continuous, "_generate_image_with_provider_fallback", fake_generate_image)
    monkeypatch.setattr(continuous, "get_settings", fake_settings)
    monkeypatch.setattr(
        continuous,
        "get_or_create_production_settings",
        fake_production_settings,
    )
    monkeypatch.setattr(continuous, "assert_project_budget_allows", fake_budget)
    monkeypatch.setattr(continuous, "_emit_continuous_video_segment_event", fake_emit)

    prepared, validation_errors = await prepare_continuous_video_flow_package(
        cast(AsyncSession, session),
        project_id,
    )

    assert validation_errors == {}
    assert [item.segment_number for item in prepared] == [1]
    assert segment.review_status == CONTINUOUS_VIDEO_REVIEW_READY
    assert segment.status == GenerationJobStatus.SUCCEEDED
    assert segment.final_frame_asset_id is not None
    assert segment.metadata_json["final_frame_asset_id"] == str(segment.final_frame_asset_id)
    assert segment.metadata_json["flow_url"] == "https://flow.google.com"
    image_assets = [item for item in session.added if isinstance(item, Asset)]
    assert len(image_assets) == 1
    assert session.commits == 1
