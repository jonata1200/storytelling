"""Regressões do enfileiramento item a item da Bíblia Visual.

Requisitos do usuário (2026-09):
1. Gerar as referências UMA A UMA dentro da etapa "Bíblia Visual" — inclusive
   individualmente, por card.
2. Quando a Meta não gera UMA das imagens, o lote deve AVANÇAR para a
   próxima em vez de abortar.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import app.ui.workspace.visual_bible_area as visual_bible_area
from app.ui.workspace.visual_bible_area import (
    _enqueue_reference_batch,
    _target_card,
)


class _FakePromptInput:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeSession:
    """Session mínima: devolve listas vazias de referências/jobs ativos."""

    async def execute(self, _statement: Any) -> Any:
        return SimpleNamespace(scalars=lambda: [])

    async def rollback(self) -> None:
        return None


def _enqueue_calls(monkeypatch: Any, behavior: dict[str, Exception]) -> list[tuple[str, str]]:
    """Patch enqueue_visual_reference_generation; behavior mapeia kind→erro."""
    calls: list[tuple[str, str]] = []

    async def fake_enqueue(
        _session: Any,
        _project_id: UUID,
        kind: str,
        _target_id: UUID,
        view_type: str,
        **_kwargs: Any,
    ) -> Any:
        calls.append((kind, view_type))
        error = behavior.get(kind)
        if error is not None:
            raise error
        return SimpleNamespace(job=None, should_dispatch=True)

    monkeypatch.setattr(
        visual_bible_area,
        "enqueue_visual_reference_generation",
        fake_enqueue,
    )
    return calls


def _prompt_inputs() -> list[tuple[str, Any, Any]]:
    def target(name: str) -> Any:
        return SimpleNamespace(id=uuid4(), name=name, canonical_profile={})

    character = target("Marcus")
    location = target("Quarto")
    return [
        ("character", character, _FakePromptInput("Prompt do Marcus.")),
        ("location", location, _FakePromptInput("Prompt do quarto.")),
    ]


async def _run_batch(
    monkeypatch: Any,
    prompt_inputs: list[tuple[str, Any, Any]] | None = None,
    behavior: dict[str, Exception] | None = None,
) -> tuple[tuple[int, int, int, int, list[str], list[str]], list[tuple[str, str]]]:
    behavior = behavior or {}
    calls = _enqueue_calls(monkeypatch, behavior)
    result = await _enqueue_reference_batch(
        _FakeSession(),  # type: ignore[arg-type]
        uuid4(),
        prompt_inputs if prompt_inputs is not None else _prompt_inputs(),
        uuid4(),
    )
    return result, calls


async def test_batch_enqueues_all_items_in_order(monkeypatch: Any) -> None:
    """O lote enfileira cada item (personagem e local) individualmente."""
    result, calls = await _run_batch(monkeypatch)

    queued, requested, already_complete, already_active, skipped, failures = result
    assert queued == 2
    assert requested == 2
    assert already_complete == already_active == 0
    assert skipped == [] and failures == []
    # Um job por item: primeiro o personagem, depois o local.
    assert calls == [("character", "full_body"), ("location", "establishing")]


async def test_batch_continues_after_enqueue_failure(monkeypatch: Any) -> None:
    """Falha ao enfileirar UM item não impede os seguintes (exigência do usuário)."""
    behavior = {"character": RuntimeError("banco indisponível")}
    result, calls = await _run_batch(monkeypatch, behavior=behavior)

    queued, _requested, _already_complete, _already_active, _skipped, failures = result
    # O local FOI enfileirado mesmo com o personagem falhando antes.
    assert calls == [("character", "full_body"), ("location", "establishing")]
    assert queued == 1
    assert failures == ["Marcus (full_body)"]


async def test_batch_skips_target_without_canonical_prompt(monkeypatch: Any) -> None:
    """Perfil sem prompt canônico é ignorado (não aborta o lote inteiro)."""
    inputs = _prompt_inputs()
    kind, target, _ = inputs[0]
    inputs[0] = (kind, target, _FakePromptInput("   "))
    result, calls = await _run_batch(monkeypatch, prompt_inputs=inputs)

    queued, _requested, _already_complete, _already_active, skipped, failures = result
    assert queued == 1
    assert skipped == ["Marcus"]
    assert failures == []
    assert calls == [("location", "establishing")]


async def test_batch_empty_when_no_targets(monkeypatch: Any) -> None:
    result, calls = await _run_batch(monkeypatch, prompt_inputs=[])

    assert result == (0, 0, 0, 0, [], [])
    assert calls == []


def test_target_card_offers_individual_generation_button() -> None:
    """Cada card de referência tem o botão de geração individual.

    Quando a referência já existe, o botão regenera APENAS aquele item;
    quando está vazia, gera somente aquele item ("Gerar referência").
    """
    source = inspect.getsource(_target_card)

    assert "generate_individual" in source
    assert '"Gerar novamente" if asset is not None else "Gerar referência"' in source
    # A geração individual usa o mesmo caminho do worker (fila IMAGE).
    assert "enqueue_visual_reference_generation" in source
    # Item a item: cada referência do card recebe o próprio botão.
    assert source.count("generate_individual_button") >= 2
