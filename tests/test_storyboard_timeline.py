from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.storyboards import service as storyboard_service
from app.storyboards.models import StoryboardFrame
from app.storyboards.service import (
    _animatic_fingerprint,
    _storyboard_prompt,
    generate_storyboard_frames,
    storyboard_coverage_errors,
)
from app.storyboards.timeline import build_visual_timeline_items, build_word_alignment
from app.storytelling.models import Scene, Script, Shot


def test_build_visual_timeline_items_is_contiguous() -> None:
    first_artifact = uuid4()
    first_asset = uuid4()
    second_artifact = uuid4()
    second_asset = uuid4()

    items = build_visual_timeline_items(
        [
            (first_artifact, first_asset, 3, {"frame": 1}),
            (second_artifact, second_asset, 2, {"frame": 2}),
        ]
    )

    assert items[0].start_ms == 0
    assert items[0].end_ms == 3000
    assert items[1].start_ms == 3000
    assert items[1].end_ms == 5000


def test_build_word_alignment_spreads_words_across_duration() -> None:
    alignment = build_word_alignment("uma promessa esquecida", 3)

    assert [item["word"] for item in alignment["words"]] == ["uma", "promessa", "esquecida"]
    assert alignment["words"][0]["start_ms"] == 0
    assert alignment["words"][-1]["end_ms"] == 3000


def test_storyboard_prompt_includes_visual_bible_context() -> None:
    scene = Scene(id=uuid4(), scene_number=1, title="Chegada")
    shot = Shot(
        id=uuid4(),
        shot_number=1,
        duration_seconds=5,
        action="Clara encontra a carta azul sobre a mesa.",
        emotion="descoberta",
        visual_composition="Plano vertical com Clara em primeiro plano.",
        camera_movement="push-in lento",
        narration_text="Clara encontra a carta.",
        dialogue_text="",
    )

    prompt = _storyboard_prompt(
        shot,
        scene,
        {
            "characters": [
                {
                    "name": "Clara",
                    "role": "filha",
                    "profile": {
                        "hair": "cabelo castanho curto",
                        "base_outfit": "casaco verde gasto",
                    },
                }
            ],
            "locations": [
                {
                    "name": "Sala da familia",
                    "description": "ambiente de revelacao",
                    "profile": {"lighting": "luz fria da janela"},
                }
            ],
            "props": [
                {
                    "name": "Carta azul",
                    "narrative_importance": "payoff da historia",
                    "profile": {"material": "papel envelhecido"},
                }
            ],
        },
    )

    assert "Biblioteca visual canonica - autoridade de continuidade" in prompt
    assert "Personagens:" in prompt
    assert "Locais:" in prompt
    assert "Objetos:" in prompt
    assert "Clara" in prompt
    assert "casaco verde gasto" in prompt
    assert "Carta azul" in prompt
    assert "primeiro frame util para image-to-video" in prompt
    assert "nenhum texto, legenda, marca d'agua" in prompt
    assert "nao criar montagem, colagem, split screen" in prompt


def test_storyboard_coverage_errors_detect_missing_and_duration_mismatch() -> None:
    first_shot_id = uuid4()
    second_shot_id = uuid4()
    scene = Scene(id=uuid4(), scene_number=1, title="Chegada")
    first_shot = Shot(id=first_shot_id, shot_number=1, duration_seconds=5)
    second_shot = Shot(id=second_shot_id, shot_number=2, duration_seconds=7)
    frame = StoryboardFrame(
        id=uuid4(),
        shot_id=first_shot_id,
        asset_id=uuid4(),
        frame_number=1,
        duration_seconds=4,
        prompt="Prompt visual completo para um quadro de storyboard vertical.",
    )

    errors = storyboard_coverage_errors([(first_shot, scene), (second_shot, scene)], [frame])

    assert "1 plano(s) sem frame de storyboard" in errors
    assert "duracao dos frames (4s) difere dos planos (12s)" in errors


@pytest.mark.asyncio
async def test_generate_storyboard_frames_requires_complete_visual_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script = Script(id=uuid4(), project_id=project_id)

    class FakeProjectRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def get_project(self, requested_project_id: object) -> object:
            assert requested_project_id == project_id
            return object()

    class FakeSession:
        async def get(self, model: object, requested_id: object) -> object | None:
            assert model is Script
            assert requested_id == script.id
            return script

    async def fake_visual_report(
        session: AsyncSession,
        requested_project_id: Any,
    ) -> dict[str, Any]:
        assert requested_project_id == project_id
        return {
            "complete": False,
            "missing_categories": [],
            "missing_views": 2,
        }

    async def fail_ordered_shots(*args: Any, **kwargs: Any) -> list[tuple[Shot, Scene]]:
        raise AssertionError("planos nao devem ser consultados antes da biblioteca visual")

    monkeypatch.setattr(storyboard_service, "ProjectRepository", FakeProjectRepository)
    monkeypatch.setattr(
        storyboard_service,
        "visual_reference_completion_report",
        fake_visual_report,
    )
    monkeypatch.setattr(storyboard_service, "_ordered_shots_for_script", fail_ordered_shots)

    with pytest.raises(ValueError, match="Biblioteca Visual"):
        await generate_storyboard_frames(cast(AsyncSession, FakeSession()), project_id, script.id)


def test_animatic_fingerprint_changes_when_frame_asset_changes() -> None:
    frame = StoryboardFrame(
        id=uuid4(),
        shot_id=uuid4(),
        asset_id=uuid4(),
        frame_number=1,
        duration_seconds=5,
        prompt="Prompt visual completo para storyboard.",
        narration_text="Clara respira fundo.",
        dialogue_text="",
        metadata_json={"frame_fingerprint": "frame-a"},
    )
    original = _animatic_fingerprint([frame])

    frame.asset_id = uuid4()

    assert _animatic_fingerprint([frame]) != original
