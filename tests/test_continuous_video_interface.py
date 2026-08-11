from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.core.enums import GenerationJobStatus
from app.generation.project_agent_routing import _contextual_project_chat_intent
from app.ui.workspace import storyboard_video_area
from app.ui.workspace.continuous_video_view_model import (
    CONTINUOUS_VIDEO_WORKFLOW_MODE,
    CONTROL_VISUAL_WORKFLOW_MODE,
    build_continuous_video_view_model,
)
from app.ui.workspace.rules import workspace_section_access
from app.video_generation.models import ContinuousVideoSegment


def _counts_without_storyboard() -> dict[str, int]:
    return {
        "briefings": 1,
        "ideas": 1,
        "scripts": 1,
        "scenes": 0,
        "shots": 0,
        "characters": 1,
        "locations": 1,
        "props": 1,
        "visual_refs": 3,
        "frames": 0,
        "animatics": 0,
        "clips": 0,
        "dubbing_jobs": 0,
        "exports": 0,
        "qa_issues": 0,
        "continuous_video_approved_segments": 0,
    }


def _segment(number: int, status: GenerationJobStatus) -> ContinuousVideoSegment:
    return ContinuousVideoSegment(
        id=uuid4(),
        project_id=uuid4(),
        segment_number=number,
        title=f"Segmento {number:02d}",
        prompt=(
            "Segmento vertical cinematografico com Clara no observatorio, relogio dourado, "
            "luz azul, movimento suave e continuidade visual sem troca de identidade."
        ),
        duration_seconds=7,
        status=status,
        provider="google_ai",
        model="veo-3.1-fast-generate-preview",
        request_fingerprint=f"{number}" * 64,
        idempotency_key=f"{number}" * 64,
        cost_estimate=Decimal("0.700000"),
        metadata_json={
            "action": f"Acao principal {number}",
            "continuity": "continuidade temporal",
            "visual_context": {"characters": [{"name": "Clara"}]},
            "characters": ["Clara"],
            "locations": ["Observatorio"],
            "props": ["Relogio"],
        },
    )


def test_continuous_mode_unlocks_video_without_storyboard() -> None:
    counts = _counts_without_storyboard()

    default_allowed, default_reason = workspace_section_access(
        "video",
        counts,
        CONTROL_VISUAL_WORKFLOW_MODE,
    )
    continuous_allowed, continuous_reason = workspace_section_access(
        "video",
        counts,
        CONTINUOUS_VIDEO_WORKFLOW_MODE,
    )

    assert default_allowed is False
    assert "storyboard" in default_reason
    assert continuous_allowed is True
    assert continuous_reason == ""


def test_missing_workflow_mode_defaults_to_continuous_video() -> None:
    allowed, reason = workspace_section_access("video", _counts_without_storyboard())

    assert allowed is True
    assert reason == ""


def test_legacy_project_with_storyboards_keeps_classic_video_access() -> None:
    counts = {
        **_counts_without_storyboard(),
        "frames": 8,
        "animatics": 1,
    }

    allowed, reason = workspace_section_access("video", counts, CONTROL_VISUAL_WORKFLOW_MODE)

    assert allowed is True
    assert reason == ""


def test_continuous_finalization_requires_approved_segment() -> None:
    counts = {
        **_counts_without_storyboard(),
        "continuous_video_segments": 2,
    }

    blocked, reason = workspace_section_access(
        "finalization",
        counts,
        CONTINUOUS_VIDEO_WORKFLOW_MODE,
    )
    counts["continuous_video_approved_segments"] = 2
    allowed, allowed_reason = workspace_section_access(
        "finalization",
        counts,
        CONTINUOUS_VIDEO_WORKFLOW_MODE,
    )

    assert blocked is False
    assert "segmento" in reason
    assert allowed is True
    assert allowed_reason == ""


def test_continuous_project_progression_skips_storyboard_requirement() -> None:
    context = {
        "production_settings": {"workflow_mode": CONTINUOUS_VIDEO_WORKFLOW_MODE},
        "counts": {
            **_counts_without_storyboard(),
            "continuous_video_segments": 0,
        },
    }

    intent = _contextual_project_chat_intent(
        "pode avançar para a próxima etapa",
        "assets",
        context,
        "chat",
    )

    assert intent.action == "generate_video"


def test_continuous_project_progression_finalizes_after_all_segments_are_approved() -> None:
    context = {
        "production_settings": {"workflow_mode": CONTINUOUS_VIDEO_WORKFLOW_MODE},
        "counts": {
            **_counts_without_storyboard(),
            "continuous_video_segments": 2,
            "continuous_video_approved_segments": 2,
        },
    }

    intent = _contextual_project_chat_intent(
        "pode avancar para a proxima etapa",
        "video",
        context,
        "chat",
    )

    assert intent.action == "generate_finalization"


def test_continuous_video_view_model_calculates_actions_and_remaining_cost() -> None:
    first = _segment(1, GenerationJobStatus.SUCCEEDED)
    second = _segment(2, GenerationJobStatus.PENDING)
    failed = _segment(3, GenerationJobStatus.FAILED)
    summary = {
        "production_settings": SimpleNamespace(workflow_mode=CONTINUOUS_VIDEO_WORKFLOW_MODE),
        "continuous_video_segments": [failed, second, first],
    }

    view_model = build_continuous_video_view_model(summary)

    assert view_model.is_continuous_mode is True
    assert [row.number for row in view_model.rows] == [1, 2, 3]
    assert view_model.generated_segments == 1
    assert view_model.pending_segments == 2
    assert view_model.failed_segments == 1
    assert view_model.remaining_cost == Decimal("1.400000")
    assert view_model.next_segment_id == second.id
    assert view_model.can_generate_next is True
    assert view_model.can_generate_all is True
    assert view_model.can_continue is True


def test_continuous_video_view_model_keeps_control_visual_mode() -> None:
    view_model = build_continuous_video_view_model(
        {
            "production_settings": SimpleNamespace(workflow_mode=CONTROL_VISUAL_WORKFLOW_MODE),
            "continuous_video_segments": [],
        }
    )

    assert view_model.is_continuous_mode is False
    assert view_model.can_generate_all is False


@pytest.mark.asyncio
async def test_generate_continuous_video_ui_handler_passes_queue_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    segment_id = uuid4()
    calls: list[dict[str, Any]] = []
    notifications: list[tuple[str, str | None]] = []
    reloads = 0

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    async def fake_generate(_session: object, requested_project_id: object, **kwargs: Any) -> tuple:
        assert requested_project_id == project_id
        calls.append(kwargs)
        return [object()], [_segment(1, GenerationJobStatus.SUCCEEDED)]

    def fake_reload() -> None:
        nonlocal reloads
        reloads += 1

    monkeypatch.setattr(storyboard_video_area, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(storyboard_video_area, "generate_continuous_video_segments", fake_generate)
    monkeypatch.setattr(
        storyboard_video_area,
        "block_if_missing_api_keys_for_step",
        lambda _step: False,
    )
    monkeypatch.setattr(
        storyboard_video_area.ui,
        "notify",
        lambda message, color=None: notifications.append((message, color)),
    )
    monkeypatch.setattr(storyboard_video_area.ui.navigate, "reload", fake_reload)

    await storyboard_video_area._generate_continuous_video_segments_from_ui(
        project_id,
        segment_ids=[segment_id],
        retry_failed=True,
        max_segments=1,
        progress_callback=lambda *_args: None,
        pause_after_current=lambda: False,
    )

    assert calls == [
        {
            "segment_ids": [segment_id],
            "retry_failed": True,
            "max_segments": 1,
            "progress_callback": calls[0]["progress_callback"],
            "pause_after_current": calls[0]["pause_after_current"],
        }
    ]
    assert notifications[-1] == ("Fila de v\u00eddeo cont\u00ednuo conclu\u00edda.", "positive")
    assert reloads == 1


@pytest.mark.asyncio
async def test_video_workflow_mode_ui_handler_saves_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    saved_payloads: list[dict[str, str]] = []

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    async def fake_update(_session: object, requested_project_id: object, payload: dict) -> object:
        assert requested_project_id == project_id
        saved_payloads.append(payload)
        return object()

    monkeypatch.setattr(storyboard_video_area, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(storyboard_video_area, "update_production_settings", fake_update)
    monkeypatch.setattr(storyboard_video_area.ui, "notify", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(storyboard_video_area.ui.navigate, "reload", lambda: None)

    await storyboard_video_area._set_video_workflow_mode_from_ui(
        project_id,
        CONTINUOUS_VIDEO_WORKFLOW_MODE,
    )

    assert saved_payloads == [{"workflow_mode": CONTINUOUS_VIDEO_WORKFLOW_MODE}]


@pytest.mark.asyncio
async def test_video_workflow_mode_ui_handler_ignores_stale_toggle_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    saved_payloads: list[dict[str, str]] = []

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    async def fake_update(_session: object, _requested_project_id: object, payload: dict) -> object:
        saved_payloads.append(payload)
        return object()

    monkeypatch.setattr(storyboard_video_area, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(storyboard_video_area, "update_production_settings", fake_update)
    monkeypatch.setattr(storyboard_video_area.ui, "notify", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(storyboard_video_area.ui.navigate, "reload", lambda: None)

    await storyboard_video_area._set_video_workflow_mode_from_ui(
        project_id,
        [0, {"value": 0, "label": "Controle visual"}],
    )

    assert saved_payloads == [{"workflow_mode": CONTINUOUS_VIDEO_WORKFLOW_MODE}]
