"""Teste de regressão: delete_continuous_video_segment não pode violar
a FK source_segment_id quando há filhos apontando para o segmento deletado.

Bug: ao deletar segmento 2, o código fazia `await session.delete(segment)`
que disparava o flush no DB. Mas se o segmento 3 (filho) tinha
source_segment_id = s2.id, o PostgreSQL lançava
ForeignKeyViolationError: update or delete on table
"continuous_video_segments" violates foreign key constraint
"fk_continuous_video_segments_source_segment_id_continuo_174c".

Causa raiz: o código limpava source_segment_id do próprio segmento
deletado e depois limpava nos filhos DENTRO da renumeração, mas a
renumeração só rodava DEPOIS do `session.delete(segment)`. No flush
dessa deleção o DB já tinha visto a FK reversa suja.

Correção: limpar source_segment_id e source_frame_asset_id em todos
os filhos ANTES de chamar session.delete().
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

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._items

    def __iter__(self) -> Any:
        return iter(self._items)


class FakeSession:
    """Mínimo necessário para delete_continuous_video_segment."""

    def __init__(self, segments: list[ContinuousVideoSegment]) -> None:
        self._segments_by_id: dict[UUID, ContinuousVideoSegment] = {
            s.id: s for s in segments
        }
        self.deleted_segments: list[UUID] = []
        self.flushed: int = 0
        # Simula a FK violation do PostgreSQL: se ainda houver
        # source_segment_id apontando para um segmento deletado no momento
        # do flush, levanta IntegrityError.
        self._fk_violation: Exception | None = None

    async def get(self, _model: Any, key: Any) -> Any:
        if _model is ContinuousVideoSegment:
            return self._segments_by_id.get(key)
        return None

    async def execute(self, stmt: Any) -> _FakeResult:
        where_clauses = getattr(stmt, "_where_clauses", None)
        order_clauses = getattr(stmt, "_order_clauses", None)
        matching = list(self._segments_by_id.values())
        if where_clauses:
            for clause in where_clauses:
                if clause.startswith("eq:project_id:"):
                    pid = UUID(clause.split(":")[-1])
                    matching = [s for s in matching if s.project_id == pid]
        if order_clauses:
            matching = sorted(matching, key=lambda s: s.segment_number)
        return _FakeResult(matching)

    async def flush(self) -> None:
        self.flushed += 1
        if self._fk_violation is not None:
            err = self._fk_violation
            self._fk_violation = None
            raise err

    async def delete(self, segment: ContinuousVideoSegment) -> None:
        # Verifica se algum outro segmento ainda referencia este via FK.
        for other in self._segments_by_id.values():
            if other.id == segment.id:
                continue
            if other.source_segment_id == segment.id:
                from sqlalchemy.exc import IntegrityError
                self._fk_violation = IntegrityError(
                    "delete violates foreign key",
                    params={},
                    orig=Exception("fk_violation"),
                )
                return
        self._segments_by_id.pop(segment.id, None)
        self.deleted_segments.append(segment.id)


class FakeSelect:
    def __init__(self) -> None:
        self._where_clauses: list[str] = []
        self._order_clauses: list[str] = []

    def where(self, clause: Any) -> "FakeSelect":
        if hasattr(clause, "name"):
            self._where_clauses.append(clause.name)
        return self

    def order_by(self, clause: Any) -> "FakeSelect":
        if hasattr(clause, "name"):
            self._order_clauses.append(clause.name)
        return self


@pytest.fixture
def patched_select(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_select(*_entities: Any) -> FakeSelect:
        return FakeSelect()

    monkeypatch.setattr(continuous_module, "select", fake_select)


@pytest.mark.asyncio
async def test_delete_segment_with_downstream_fk_does_not_violate_fk(
    patched_select: None,
) -> None:
    """Regressão: deletar segmento 2 quando segmento 3 (filho) tem
    source_segment_id = s2.id não pode levantar ForeignKeyViolationError.

    Cenário exato do bug reportado: 'update or delete on table
    continuous_video_segments violates foreign key constraint
    fk_continuous_video_segments_source_segment_id_continuo_174c'.
    """
    project_id = uuid.uuid4()
    s1 = _make_segment(project_id=project_id, segment_number=1)
    s2 = _make_segment(
        project_id=project_id,
        segment_number=2,
        source_frame_asset_id=uuid.uuid4(),
    )
    # s3 é o "filho" de s2 — herdava o frame inicial de s2. Esta é a
    # referência FK reversa que violava a constraint.
    s3 = _make_segment(
        project_id=project_id,
        segment_number=3,
        source_segment_id=s2.id,
        source_frame_asset_id=uuid.uuid4(),
    )
    session = FakeSession([s1, s2, s3])

    # Sem o fix: levanta IntegrityError. Com o fix: completa e zera
    # a referência reversa de s3.
    result = await delete_continuous_video_segment(session, project_id, s2.id)

    assert result is True
    # s3 foi renumerado para 2 e perdeu a referência ao deletado.
    assert s3.source_segment_id is None
    assert s3.source_frame_asset_id is None
    assert s3.segment_number == 2
    assert s2.id in session.deleted_segments


@pytest.mark.asyncio
async def test_delete_segment_clears_fk_before_session_delete(
    patched_select: None,
) -> None:
    """Garante a ORDEM das operações: source_segment_id reverso é zerado
    ANTES de session.delete() ser chamado (para que o flush da deleção
    não levante FK violation).
    """
    project_id = uuid.uuid4()
    s1 = _make_segment(project_id=project_id, segment_number=1)
    s2 = _make_segment(project_id=project_id, segment_number=2)
    s3 = _make_segment(
        project_id=project_id,
        segment_number=3,
        source_segment_id=s2.id,
    )
    session = FakeSession([s1, s2, s3])

    await delete_continuous_video_segment(session, project_id, s2.id)

    # s3 deve ter sido limpo ANTES da deleção de s2 chegar ao flush
    # (assert já é feito por não levantar exception, mas reforçamos
    # o estado final).
    assert s3.source_segment_id is None
    # E s2 precisa ter sido de fato deletado.
    assert s2.id in session.deleted_segments