from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.core.enums import GenerationJobStatus, GenerationJobType
from app.generation.models import PromptExecution
from app.observability.middleware import correlation_id_var
from app.observability.redaction import redact_mapping, redact_secrets
from app.observability.schemas import OperationalEventCreate
from app.observability.service import (
    _provider_channel_readiness,
    _veo_ai_free_session_readiness,
    emit_project_event,
    project_execution_summary,
)
from app.video_generation.models import GenerationJob


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


def test_provider_channel_readiness_reports_new_provider_components() -> None:
    settings = Settings(
        ai_provider="nvidia_nim",
        text_provider="",
        image_provider="veo_ai_free",
        video_provider="veo_ai_free",
        nvidia_nim_api_key="nv-secret",
        nvidia_nim_default_model="z-ai/glm-5.2",
        veo_ai_free_image_model="veo-ai-free/image",
        veo_ai_free_video_model="veo-ai-free/video",
    )

    text = _provider_channel_readiness(settings, "text")
    image = _provider_channel_readiness(settings, "image")
    video = _provider_channel_readiness(settings, "video")

    assert text.name == "text_provider"
    assert image.name == "image_provider"
    assert video.name == "video_provider"
    assert {text.status, image.status, video.status} == {"ready"}
    assert text.details["provider"] == "nvidia_nim"
    assert image.details["model"] == "veo-ai-free/image"
    assert video.details["api_key_configured"] == "false"


def test_provider_channel_readiness_reports_missing_veo_model() -> None:
    settings = Settings(image_provider="veo_ai_free", veo_ai_free_image_model="")

    image = _provider_channel_readiness(settings, "image")

    assert image.name == "image_provider"
    assert image.status == "degraded"
    assert image.details["provider"] == "veo_ai_free"
    assert "VEO_AI_FREE_IMAGE_MODEL" in image.message


def test_provider_channel_readiness_reports_no_text_fallbacks() -> None:
    settings = Settings(
        ai_provider="omniroute",
        text_provider="nvidia_nim",
        text_provider_fallbacks="",
        nvidia_nim_api_key="nv-secret",
        nvidia_nim_default_model="z-ai/glm-5.2",
    )

    text = _provider_channel_readiness(settings, "text")

    assert text.status == "ready"
    assert text.details["provider"] == "nvidia_nim"
    assert text.details["fallbacks"] == ""
    assert text.details["api_key_configured"] == "true"


def test_provider_channel_readiness_reports_missing_nvidia_key() -> None:
    settings = Settings(
        ai_provider="omniroute",
        text_provider="nvidia_nim",
        nvidia_nim_api_key=None,
        nvidia_nim_default_model="z-ai/glm-5.2",
    )

    text = _provider_channel_readiness(settings, "text")

    assert text.status == "degraded"
    assert "NVIDIA_NIM_API_KEY" in text.message


def test_veo_ai_free_session_readiness_uses_local_validator(tmp_path: Path) -> None:
    settings = Settings(
        veo_ai_free_enabled=True,
        veo_ai_free_session_path=tmp_path / "missing.json",
    )

    component = _veo_ai_free_session_readiness(settings)

    assert component.name == "veo_ai_free_session"
    assert component.status == "degraded"
    assert component.details["enabled"] == "true"
    assert component.details["session_status"] == "unknown"


class _FakeEventSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)


class _FakePromptResult:
    def __init__(self, rows: list[tuple[PromptExecution, str | None]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[PromptExecution, str | None]]:
        return self.rows


class _FakeJobResult:
    def __init__(self, jobs: list[GenerationJob]) -> None:
        self.jobs = jobs

    def scalars(self) -> list[GenerationJob]:
        return self.jobs


class _FakeExecutionSummarySession:
    def __init__(
        self,
        prompt_rows: list[tuple[PromptExecution, str | None]],
        jobs: list[GenerationJob],
    ) -> None:
        self.results: list[Any] = [_FakePromptResult(prompt_rows), _FakeJobResult(jobs)]

    async def execute(self, _statement: Any) -> Any:
        return self.results.pop(0)


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


@pytest.mark.asyncio
async def test_project_execution_summary_groups_prompts_and_redacts_jobs() -> None:
    project_id = uuid4()
    now = datetime.now(UTC)
    first = PromptExecution(
        id=uuid4(),
        project_id=project_id,
        provider="omniroute",
        model="writer/model",
        prompt="prompt",
        variables={},
        response={},
        parameters={},
        estimated_cost=Decimal("0.100000"),
        duration_ms=1000,
    )
    first.created_at = now
    second = PromptExecution(
        id=uuid4(),
        project_id=project_id,
        provider="omniroute",
        model="writer/model",
        prompt="prompt",
        variables={},
        response={},
        parameters={},
        estimated_cost=Decimal("0.200000"),
        duration_ms=3000,
    )
    second.created_at = now
    job = GenerationJob(
        id=uuid4(),
        project_id=project_id,
        job_type=GenerationJobType.ANALYSIS,
        status=GenerationJobStatus.FAILED,
        progress=100,
        attempts=1,
        max_attempts=3,
        provider="omniroute",
        model="writer/model",
        idempotency_key="job-key",
        request_payload={"step": "script", "payload": {"api_key": "secret-token"}},
        response_payload={},
        cost_estimate=Decimal("0.300000"),
        error="Authorization: Bearer sk-secret",
    )
    job.created_at = now
    session = _FakeExecutionSummarySession([(first, "script"), (second, "script")], [job])

    summary = await project_execution_summary(cast(AsyncSession, session), project_id)

    metric = summary.prompt_metrics[0]
    assert metric.task == "script"
    assert metric.count == 2
    assert metric.average_duration_ms == 2000
    assert metric.max_duration_ms == 3000
    assert metric.estimated_cost == Decimal("0.300000")
    assert summary.recent_jobs[0].step == "script"
    assert "sk-secret" not in str(summary.recent_jobs[0].error)
