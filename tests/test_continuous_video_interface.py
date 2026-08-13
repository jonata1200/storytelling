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
        "exports": 0,
        "qa_issues": 0,
        "continuous_video_done_segments": 0,
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
        provider="flow_assistant",
        model="google_flow",
        request_fingerprint=f"{number}" * 64,
        idempotency_key=f"{number}" * 64,
        cost_estimate=Decimal("0.000000"),
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


def test_continuous_video_unlocked_without_props_when_refs_complete() -> None:
    counts = {
        **_counts_without_storyboard(),
        "characters": 2,
        "locations": 1,
        "props": 0,
        "visual_refs": 3,
        "continuous_video_segments": 0,
    }

    allowed, reason = workspace_section_access(
        "video",
        counts,
        CONTINUOUS_VIDEO_WORKFLOW_MODE,
    )

    assert allowed is True
    assert reason == ""


def test_visual_bible_still_requires_characters_and_locations_without_props() -> None:
    counts = {
        **_counts_without_storyboard(),
        "characters": 2,
        "locations": 1,
        "props": 0,
        "visual_refs": 1,
        "continuous_video_segments": 0,
    }

    blocked, reason = workspace_section_access(
        "video",
        counts,
        CONTINUOUS_VIDEO_WORKFLOW_MODE,
    )

    assert blocked is False
    assert "imagens" in reason

    counts["locations"] = 0
    blocked, reason = workspace_section_access(
        "video",
        counts,
        CONTINUOUS_VIDEO_WORKFLOW_MODE,
    )
    assert blocked is False
    assert "imagens" in reason


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


def test_continuous_project_progression_finalizes_after_all_segments_are_done() -> None:
    context = {
        "production_settings": {"workflow_mode": CONTINUOUS_VIDEO_WORKFLOW_MODE},
        "counts": {
            **_counts_without_storyboard(),
            "continuous_video_segments": 2,
            "continuous_video_done_segments": 2,
        },
    }

    intent = _contextual_project_chat_intent(
        "pode avancar para a proxima etapa",
        "video",
        context,
        "chat",
    )

    assert intent.action == "chat"


def test_continuous_video_view_model_calculates_actions_and_prepare_state() -> None:
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
    assert view_model.next_segment_id == second.id
    assert view_model.can_plan is True
    assert view_model.can_prepare is True
    assert view_model.can_conclude is False


def test_continuous_video_view_model_keeps_control_visual_mode() -> None:
    view_model = build_continuous_video_view_model(
        {
            "production_settings": SimpleNamespace(workflow_mode=CONTROL_VISUAL_WORKFLOW_MODE),
            "continuous_video_segments": [],
        }
    )

    assert view_model.is_continuous_mode is False
    assert view_model.can_prepare is False
    assert view_model.can_conclude is False


@pytest.mark.asyncio
async def test_prepare_continuous_video_flow_package_ui_handler_passes_segment_ids(
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

    async def fake_prepare(_session: object, requested_project_id: object, **kwargs: Any) -> tuple:
        assert requested_project_id == project_id
        calls.append(kwargs)
        return [_segment(1, GenerationJobStatus.SUCCEEDED)], {}

    def fake_reload() -> None:
        nonlocal reloads
        reloads += 1

    def fake_safe_notify(message: str, **kwargs: Any) -> bool:
        notifications.append((message, kwargs.get("color")))
        return True

    monkeypatch.setattr(storyboard_video_area, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(
        storyboard_video_area,
        "prepare_continuous_video_flow_package",
        fake_prepare,
    )
    monkeypatch.setattr(
        storyboard_video_area,
        "block_if_missing_api_keys_for_step",
        lambda _step: False,
    )
    monkeypatch.setattr(storyboard_video_area, "_safe_notify", fake_safe_notify)
    monkeypatch.setattr(storyboard_video_area, "_safe_reload", fake_reload)

    await storyboard_video_area._prepare_continuous_video_flow_package_from_ui(
        project_id,
        segment_ids=[segment_id],
    )

    assert calls == [{"segment_ids": [segment_id]}]
    assert notifications[-1] == ("Pacote para o Google Flow pronto!", "positive")
    assert reloads == 1


@pytest.mark.asyncio
async def test_prepare_continuous_video_flow_package_ui_handler_ignores_removed_page_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    async def fake_prepare(*_args: Any, **_kwargs: Any) -> tuple:
        return [_segment(1, GenerationJobStatus.SUCCEEDED)], {}

    def stale_notify(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("The client this element belongs to has been deleted.")

    monkeypatch.setattr(storyboard_video_area, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(
        storyboard_video_area,
        "prepare_continuous_video_flow_package",
        fake_prepare,
    )
    monkeypatch.setattr(
        storyboard_video_area,
        "block_if_missing_api_keys_for_step",
        lambda _step: False,
    )
    monkeypatch.setattr(storyboard_video_area, "ui", SimpleNamespace(notify=stale_notify))

    await storyboard_video_area._prepare_continuous_video_flow_package_from_ui(project_id)


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
