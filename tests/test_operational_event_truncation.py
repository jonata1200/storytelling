"""Testes do truncamento de message em OperationalEventCreate.

Bug: a mensagem do Playwright (Call log + traceback) tem >2000 chars. O
schema OperationalEventCreate.message tem max_length=2000 → Pydantic
ValidationError → cascata MissingGreenlet que trava o worker em
estado de erro sem reportar nada útil.

Correção: helper _safe_event_message() que trunca em 2000 chars com
indicador [...truncado]. Erro completo fica em metadata.details.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.video_generation.continuous_package import _safe_event_message


def test_safe_event_message_short_text_passes_through() -> None:
    """Texto <2000 chars não é modificado."""
    text = "Erro de teste: conexão recusada"
    assert _safe_event_message(text) == text


def test_safe_event_message_truncates_long_text() -> None:
    """Texto >1900 chars é truncado com indicador [...truncado]."""
    long_text = "x" * 5000
    result = _safe_event_message(long_text, limit=1900)
    # O resultado deve conter os primeiros 1900 chars + sufixo de truncamento
    assert result.startswith("x" * 1900)
    assert "[...truncado, 5000 → 1900 chars]" in result
    assert len(result) < len(long_text)


def test_safe_event_message_handles_none() -> None:
    """None vira string vazia."""
    assert _safe_event_message(None) == ""


def test_safe_event_message_respects_custom_limit() -> None:
    """Limite customizado é respeitado."""
    long_text = "x" * 300
    result = _safe_event_message(long_text, limit=100)
    assert result.startswith("x" * 100)
    assert "[...truncado, 300 → 100 chars]" in result
    assert len(result) < len(long_text)


def test_emit_continuous_video_segment_event_with_long_message() -> None:
    """Verificação de regressão: o schema OperationalEventCreate aceita
    o resultado de _safe_event_message(str(exc)) quando exc tem 5000 chars
    (cenário real do bug)."""
    from app.observability.schemas import OperationalEventCreate
    from uuid import uuid4

    long_text = "browserType.launchPersistentContext: Target page, context or browser has been closed\n" + ("x" * 5000)
    safe = _safe_event_message(long_text)
    # Não deve levantar ValidationError
    event = OperationalEventCreate(
        project_id=uuid4(),
        event_type="continuous_video_segment",
        status="failed",
        provider="vibes",
        model="vibes",
        message=safe,
    )
    assert len(event.message) <= 2000