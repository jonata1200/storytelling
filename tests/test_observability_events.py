from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.observability.middleware import correlation_id_var
from app.observability.redaction import redact_mapping, redact_secrets
from app.observability.schemas import OperationalEventCreate
from app.observability.service import _provider_channel_readiness, emit_project_event


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


def test_redact_secrets_masks_omniroute_api_key_assignments() -> None:
    text = "Authorization: Bearer omni-secret-token OMNIROUTE_API_KEY=another-secret"

    redacted = redact_secrets(text)

    assert "omni-secret-token" not in redacted
    assert "another-secret" not in redacted
    assert "[REDACTED]" in redacted


def test_provider_channel_readiness_reports_omniroute_media_components() -> None:
    settings = Settings(
        ai_provider="omniroute",
        omniroute_api_key="omni-secret",
        omniroute_default_model="vendor/text",
        omniroute_image_model="vendor/image",
        omniroute_video_model="vendor/video",
    )

    text = _provider_channel_readiness(settings, "text")
    image = _provider_channel_readiness(settings, "image")
    video = _provider_channel_readiness(settings, "video")

    assert text.name == "text_provider"
    assert image.name == "image_provider"
    assert video.name == "video_provider"
    assert {text.status, image.status, video.status} == {"ready"}
    assert text.details["provider"] == "omniroute"
    assert image.details["model"] == "vendor/image"
    assert video.details["api_key_configured"] == "true"


def test_provider_channel_readiness_keeps_openrouter_rollback_visible() -> None:
    settings = Settings(ai_provider="omniroute", image_provider="openrouter")

    image = _provider_channel_readiness(settings, "image")

    assert image.name == "image_provider"
    assert image.status == "degraded"
    assert image.details["provider"] == "openrouter"
    assert "OPENROUTER_API_KEY" in image.message


class _FakeEventSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)


@pytest.mark.asyncio
async def test_emit_project_event_persists_redacted_correlation_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _FakeEventSession()
    token = correlation_id_var.set("cid-test")
    caplog.set_level("INFO", logger="app.observability.service")
    try:
        event = await emit_project_event(
            cast(AsyncSession, session),
            OperationalEventCreate(
                project_id=uuid4(),
                event_type="provider_call",
                status="failed",
                provider="omniroute",
                model="vendor/model",
                operation="text_generation",
                estimated_cost=Decimal("0.25"),
                message="erro com sk-or-secret-token",
                details={"api_key": "abc123", "reason": "token=hidden"},
            ),
        )
    finally:
        correlation_id_var.reset(token)

    assert session.added == [event]
    assert event.correlation_id == "cid-test"
    assert event.provider == "omniroute"
    assert event.model == "vendor/model"
    assert event.operation == "text_generation"
    assert "sk-or-secret-token" not in event.message
    assert event.details["api_key"] == "[REDACTED]"
    assert "hidden" not in event.details["reason"]
    record = next(item for item in caplog.records if item.message == "operational_event")
    assert record.__dict__["provider"] == "omniroute"
    assert record.__dict__["model"] == "vendor/model"
    assert record.__dict__["operation"] == "text_generation"
