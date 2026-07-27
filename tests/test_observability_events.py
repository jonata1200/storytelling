from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.middleware import correlation_id_var
from app.observability.redaction import redact_mapping, redact_secrets
from app.observability.schemas import OperationalEventCreate
from app.observability.service import emit_project_event


def test_redact_secrets_masks_keys_and_bearer_tokens() -> None:
    text = "Authorization: Bearer sk-or-secret-token api_key=abc123"

    redacted = redact_secrets(text)

    assert "sk-or-secret-token" not in redacted
    assert "abc123" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_mapping_masks_nested_secret_values() -> None:
    redacted = redact_mapping(
        {"safe": "ok", "nested": {"token": "abc", "message": "password=secret"}}
    )

    assert redacted["safe"] == "ok"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert "secret" not in redacted["nested"]["message"]


class _FakeEventSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)


@pytest.mark.asyncio
async def test_emit_project_event_persists_redacted_correlation_context() -> None:
    session = _FakeEventSession()
    token = correlation_id_var.set("cid-test")
    try:
        event = await emit_project_event(
            cast(AsyncSession, session),
            OperationalEventCreate(
                project_id=uuid4(),
                event_type="provider_call",
                status="failed",
                estimated_cost=Decimal("0.25"),
                message="erro com sk-or-secret-token",
                details={"api_key": "abc123", "reason": "token=hidden"},
            ),
        )
    finally:
        correlation_id_var.reset(token)

    assert session.added == [event]
    assert event.correlation_id == "cid-test"
    assert "sk-or-secret-token" not in event.message
    assert event.details["api_key"] == "[REDACTED]"
    assert "hidden" not in event.details["reason"]
