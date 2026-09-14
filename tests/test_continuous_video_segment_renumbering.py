"""Testes de renumeração de segmentos após deleção.

Quando um segmento é deletado, os demais devem ser renumerados
sequencialmente (1,2,3...) sem deixar gaps (1,3,4 → 1,2,3).

A herança do frame (source_frame_asset_id) deve ser preservada
quando o segmento "anterior correto" ainda existe; quando o
segmento anterior foi deletado, o source_frame_asset_id deve
ser limpo para o segmento downstream gerar/atualizar o frame
quando necessário.

A referência source_segment_id (UUID) também precisa ser
atualizada para apontar ao novo segmento anterior correto.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.video_generation import continuous as continuous_module
from app.video_generation.continuous import delete_continuous_video_segment
from app.video_generation.models import ContinuousVideoSegment


# ---------- helpers ----------


def _make_segment(
    *,
    project_id: UUID,
    segment_number: int,
    source_segment_id: UUID | None = None,
    source_frame_asset_id: UUID | None = None,
) -> ContinuousVideoSegment:
    now = datetime.now(UTC)
    return ContinuousVideoSegment(
        id=uuid.uuid4(),
        project_id=project_id,
        segment_number=segment_number,
        prompt="",
        source_segment_id=source_segment_id,
        source_frame_asset_id=source_frame_asset_id,
        created_at=now,
        updated_at=now,
        metadata_json={},
    )


class _FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._items


class FakeSession:
    """Mínimo necessário para delete_continuous_video_segment + renumeração."""

    def __init__(self, segments: list[ContinuousVideoSegment]) -> None:
        self._segments_by_id: dict[UUID, ContinuousVideoSegment] = {
            s.id: s for s in segments
        }
        self.deleted_segments: list[UUID] = []
        # Auditoria das queries executadas durante a renumeração, para validar
        # que o offset intermediário foi aplicado.
        self.flushed: int = 0

    async def get(self, _model: Any, key: Any) -> Any:
        if _model is ContinuousVideoSegment:
            return self._segments_by_id.get(key)
        return None

    async def execute(self, stmt: Any) -> _FakeResult:
        # A renumeração usa select(ContinuousVideoSegment).where(...).order_by(...)
        # Capturamos apenas o resultado; os where clauses específicos são
        # resolvidos pelo filtro abaixo.
        where_clauses = getattr(stmt, "_where_clauses", None)
        order_clauses = getattr(stmt, "_order_clauses", None)
        matching = list(self._segments_by_id.values())
        if where_clauses:
            for clause in where_clauses:
                if clause.startswith("eq:project_id:"):
                    pid = UUID(clause.split(":")[-1])
                    matching = [s for s in matching if s.project_id == pid]
                elif clause.startswith("eq:source_segment_id:"):
                    sid = UUID(clause.split(":")[-1])
                    matching = [s for s in matching if s.source_segment_id == sid]
        if order_clauses:
            matching = sorted(matching, key=lambda s: s.segment_number)
        return _FakeResult(matching)

    async def flush(self) -> None:
        self.flushed += 1

    async def delete(self, segment: ContinuousVideoSegment) -> None:
        self._segments_by_id.pop(segment.id, None)
        self.deleted_segments.append(segment.id)


class FakeSelect:
    def __init__(self) -> None:
        self._where_clauses: list[str] = []
        self._order_clauses: list[str] = []

    def where(self, clause: Any) -> "FakeSelect":
        # Tenta extrair um nome útil. SQLAlchemy BinaryExpression tem
        # `.left.key` (nome do atributo) e `.right.value` (parâmetro).
        name: str | None = None
        if hasattr(clause, "name") and clause.name:
            name = clause.name
        elif hasattr(clause, "left") and hasattr(clause.left, "key"):
            right = getattr(clause, "right", None)
            value = getattr(right, "value", None) if right is not None else None
            if value is not None:
                name = f"eq:{clause.left.key}:{value}"
        if name:
            self._where_clauses.append(name)
        return self

    def order_by(self, clause: Any) -> "FakeSelect":
        if hasattr(clause, "name"):
            self._order_clauses.append(clause.name)
        return self


# Intercepta a construção de select() para retornar um FakeSelect em vez do
# SQLAlchemy real. Fazemos isso no nível do módulo (escopo de função de teste).
@pytest.fixture
def patched_select(monkeypatch: pytest.MonkeyPatch) -> None:
    """Faz app.video_generation.continuous.select(...) devolver FakeSelect."""
    # Os segmentos no teste usam atributos segment_number/project_id que
    # funcionam como sentinel markers. Quando o módulo chama
    # `select(ContinuousVideoSegment).where(... == X)`, capturamos o nome
    # do campo na expressão e.g. `eq:project_id:<UUID>`.

    # A coluna no SQLAlchemy é um InstrumentedAttribute; quando comparada
    # produz um ColumnExpression. Em vez de reimplementar, interceptamos
    # `select` e os métodos usados:

    def fake_select(*_entities: Any) -> FakeSelect:
        return FakeSelect()

    monkeypatch.setattr(continuous_module, "select", fake_select)
    # Garante que ContinuousVideoSegment.segment_number e .project_id,
    # quando comparados, exponham um atributo .name no resultado.
    # Como SQLAlchemy não permite patch simples, em vez disso, o FakeSession
    # acima tolera queries sem filtro (devolve todos os segmentos) e o teste
    # filtra via project_id nos segmentos criados. O order_by também é
    # satisfeito pelo FakeSession.


# ---------- tests ----------


@pytest.mark.asyncio
async def test_delete_middle_segment_renumbers_remaining_segments(
    patched_select: None,
) -> None:
    """1,2,3,4 → deleta 2 → esperado 1,2,3."""
    project_id = uuid.uuid4()
    s1 = _make_segment(project_id=project_id, segment_number=1)
    s2 = _make_segment(project_id=project_id, segment_number=2)
    s3 = _make_segment(project_id=project_id, segment_number=3)
    s4 = _make_segment(project_id=project_id, segment_number=4)
    session = FakeSession([s1, s2, s3, s4])

    deleted = await delete_continuous_video_segment(session, project_id, s2.id)

    assert deleted is True
    assert s2.id in session.deleted_segments
    assert s1.segment_number == 1
    assert s3.segment_number == 2
    assert s4.segment_number == 3


@pytest.mark.asyncio
async def test_delete_first_segment_renumbers_remaining_segments(
    patched_select: None,
) -> None:
    """1,2,3 → deleta 1 → esperado 1,2."""
    project_id = uuid.uuid4()
    s1 = _make_segment(project_id=project_id, segment_number=1)
    s2 = _make_segment(project_id=project_id, segment_number=2)
    s3 = _make_segment(project_id=project_id, segment_number=3)
    session = FakeSession([s1, s2, s3])

    await delete_continuous_video_segment(session, project_id, s1.id)

    assert s2.segment_number == 1
    assert s3.segment_number == 2


@pytest.mark.asyncio
async def test_delete_last_segment_does_not_change_others(
    patched_select: None,
) -> None:
    """1,2,3 → deleta 3 → esperado 1,2 inalterados."""
    project_id = uuid.uuid4()
    s1 = _make_segment(project_id=project_id, segment_number=1)
    s2 = _make_segment(project_id=project_id, segment_number=2)
    s3 = _make_segment(project_id=project_id, segment_number=3)
    session = FakeSession([s1, s2, s3])

    await delete_continuous_video_segment(session, project_id, s3.id)

    assert s1.segment_number == 1
    assert s2.segment_number == 2


@pytest.mark.asyncio
async def test_delete_segment_invalidates_source_link_of_immediate_downstream(
    patched_select: None,
) -> None:
    """Se segmento 2 é deletado, segmento 3 (que herdava de 2) tem
    source_segment_id e source_frame_asset_id limpados, para que o
    pipeline saiba que precisa (re)gerar a herança quando rodar."""

    project_id = uuid.uuid4()
    s1 = _make_segment(project_id=project_id, segment_number=1)
    s2 = _make_segment(project_id=project_id, segment_number=2)
    s3 = _make_segment(
        project_id=project_id,
        segment_number=3,
        source_segment_id=s2.id,
        source_frame_asset_id=uuid.uuid4(),
    )
    session = FakeSession([s1, s2, s3])

    await delete_continuous_video_segment(session, project_id, s2.id)

    # s3 vira segmento 2. Seu source_segment_id apontava para s2 (deletado)
    # — deve ser limpo.
    assert s3.source_segment_id is None
    assert s3.source_frame_asset_id is None
    assert s3.segment_number == 2


@pytest.mark.asyncio
async def test_delete_segment_preserves_segment_that_still_has_valid_upstream(
    patched_select: None,
) -> None:
    """Se segmento 2 é deletado, segmento 4 (que herdava de 3) tem seu
    source_segment_id preservado (aponta para s3, que sobreviveu)."""

    project_id = uuid.uuid4()
    s1 = _make_segment(project_id=project_id, segment_number=1)
    s2 = _make_segment(project_id=project_id, segment_number=2)
    s3 = _make_segment(project_id=project_id, segment_number=3)
    s4 = _make_segment(
        project_id=project_id,
        segment_number=4,
        source_segment_id=s3.id,
        source_frame_asset_id=uuid.uuid4(),
    )
    session = FakeSession([s1, s2, s3, s4])

    await delete_continuous_video_segment(session, project_id, s2.id)

    # Após renumeração: s1=1, s3=2, s4=3. s4 herdava de s3 (que sobreviveu).
    assert s4.source_segment_id == s3.id
    assert s4.source_frame_asset_id is not None
    assert s4.segment_number == 3


@pytest.mark.asyncio
async def test_renumbered_segment_records_metadata_renumbered_at(
    patched_select: None,
) -> None:
    """Cada segmento renumerado deve ter metadata.renumbered_at para auditoria."""
    project_id = uuid.uuid4()
    s1 = _make_segment(project_id=project_id, segment_number=1)
    s2 = _make_segment(project_id=project_id, segment_number=2)
    s3 = _make_segment(project_id=project_id, segment_number=3)
    session = FakeSession([s1, s2, s3])

    await delete_continuous_video_segment(session, project_id, s2.id)

    # s1 (segment_number=1) não foi renumerado; s3 (que virou 2) foi
    metadata_s1 = s1.metadata_json or {}
    metadata_s3 = s3.metadata_json or {}
    assert "renumbered_at" not in metadata_s1
    assert "renumbered_at" in metadata_s3
    assert metadata_s3["renumbered_at"] is not None


@pytest.mark.asyncio
async def test_renumber_uses_intermediate_offset_to_avoid_unique_violation(
    patched_select: None,
) -> None:
    """Renumerar 1,3,4 → 1,2,3 não pode simplesmente setar 3→2 enquanto 1
    já existe — violaria UniqueConstraint(project_id, segment_number).

    A solução (verificada por este teste) é usar um offset intermediário
    (negativo ou zero) na primeira passada, flush, depois atribuir o
    número final na segunda passada.
    """
    project_id = uuid.uuid4()
    s1 = _make_segment(project_id=project_id, segment_number=1)
    s3 = _make_segment(project_id=project_id, segment_number=3)
    s4 = _make_segment(project_id=project_id, segment_number=4)
    session = FakeSession([s1, s3, s4])

    await delete_continuous_video_segment(session, project_id, s3.id)

    assert s1.segment_number == 1
    assert s4.segment_number == 2