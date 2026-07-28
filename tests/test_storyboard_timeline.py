import asyncio
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.image.types import ImageGenerationRequest, ImageResult
from app.storyboards import prompt_approvals
from app.storyboards import service as storyboard_service
from app.storyboards.frame_generation import (
    StoryboardFrameGenerationPlan,
    generate_storyboard_plan_images,
    storyboard_image_concurrency,
)
from app.storyboards.models import StoryboardFrame
from app.storyboards.prompts import (
    _store_storyboard_prompt_approval,
    _store_storyboard_prompt_override,
    _storyboard_effective_prompt,
    _storyboard_prompt,
    _storyboard_prompt_is_approved,
)
from app.storyboards.service import (
    _animatic_fingerprint,
    _local_storage_file_exists,
    approve_storyboard_prompt,
    generate_storyboard_frames,
    storyboard_coverage_errors,
    update_storyboard_prompt,
)
from app.storyboards.timeline import build_visual_timeline_items, build_word_alignment
from app.storyboards.workflow import _selected_storyboard_shots
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
    assert "não criar montagem, colagem, split screen" in prompt


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
    assert "duração dos frames (4s) difere dos planos (12s)" in errors


def test_storyboard_prompt_approval_requires_matching_hash() -> None:
    script_id = uuid4()
    shot_id = uuid4()
    metadata = _store_storyboard_prompt_approval({}, script_id, shot_id, "hash-a")

    assert _storyboard_prompt_is_approved(metadata, script_id, shot_id, "hash-a")
    assert not _storyboard_prompt_is_approved(metadata, script_id, shot_id, "hash-b")


def test_storyboard_prompt_override_invalidates_previous_approval() -> None:
    script_id = uuid4()
    shot_id = uuid4()
    metadata = _store_storyboard_prompt_approval({}, script_id, shot_id, "hash-a")

    metadata = _store_storyboard_prompt_override(
        metadata,
        script_id,
        shot_id,
        "Prompt editado para este plano.",
    )

    assert _storyboard_effective_prompt(metadata, script_id, shot_id, "Prompt original") == (
        "Prompt editado para este plano."
    )
    assert not _storyboard_prompt_is_approved(metadata, script_id, shot_id, "hash-a")


def test_storyboard_image_concurrency_is_bounded() -> None:
    assert storyboard_image_concurrency(None) == 3
    assert storyboard_image_concurrency("invalid") == 3
    assert storyboard_image_concurrency(0) == 3
    assert storyboard_image_concurrency(1) == 1
    assert storyboard_image_concurrency(20) == 6


@pytest.mark.asyncio
async def test_generate_storyboard_plan_images_respects_concurrency_limit(
    tmp_path: Path,
) -> None:
    active_generations = 0
    max_active_generations = 0
    lock = asyncio.Lock()

    class FakeProvider:
        async def generate(self, request: ImageGenerationRequest) -> ImageResult:
            nonlocal active_generations, max_active_generations
            async with lock:
                active_generations += 1
                max_active_generations = max(max_active_generations, active_generations)
            await asyncio.sleep(0.01)
            async with lock:
                active_generations -= 1
            file_path = tmp_path / f"{request.target_id}.png"
            file_path.write_bytes(b"image")
            return ImageResult(
                file_path=file_path,
                storage_uri=file_path.as_posix(),
                sha256=request.target_id,
                content_type="image/png",
                provider="fake",
                model=request.model,
                prompt=request.prompt,
            )

        async def edit(self, request: object) -> ImageResult:
            raise NotImplementedError

    scene = Scene(id=uuid4(), scene_number=1)
    plans = [
        StoryboardFrameGenerationPlan(
            shot=Shot(id=uuid4(), shot_number=index + 1, artifact_id=uuid4()),
            scene=scene,
            frame_number=index + 1,
            prompt=f"Prompt {index + 1}",
            existing_frame=None,
            needs_image=True,
            asset_artifact_id=uuid4(),
        )
        for index in range(4)
    ]

    await generate_storyboard_plan_images(
        FakeProvider(),
        plans,
        output_dir=tmp_path,
        image_resolution="1K",
        image_model="fake-model",
        concurrency=2,
    )

    assert max_active_generations == 2
    assert all(plan.image is not None for plan in plans)
    assert all(plan.duration_ms for plan in plans)


@pytest.mark.asyncio
async def test_approve_storyboard_prompt_stores_single_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script_id = uuid4()
    shot_id = uuid4()

    class FakeSettings:
        metadata_json: dict[str, Any] = {}

    class FakeSession:
        committed = False

        async def commit(self) -> None:
            self.committed = True

    async def fake_previews(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["shot_id"] == shot_id
        return [
            {
                "shot_id": shot_id,
                "prompt_hash": "hash-a",
                "approved": False,
            }
        ]

    async def fake_settings(*args: Any, **kwargs: Any) -> FakeSettings:
        return settings

    settings = FakeSettings()
    session = FakeSession()
    monkeypatch.setattr(prompt_approvals, "list_storyboard_prompt_previews", fake_previews)
    monkeypatch.setattr(prompt_approvals, "get_or_create_production_settings", fake_settings)

    approved = await approve_storyboard_prompt(
        cast(AsyncSession, session),
        project_id,
        script_id,
        shot_id,
    )

    assert approved is True
    assert session.committed is True
    assert _storyboard_prompt_is_approved(settings.metadata_json, script_id, shot_id, "hash-a")


@pytest.mark.asyncio
async def test_update_storyboard_prompt_saves_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script_id = uuid4()
    shot_id = uuid4()

    class FakeSettings:
        metadata_json: dict[str, Any] = {}

    class FakeSession:
        committed = False

        async def commit(self) -> None:
            self.committed = True

    async def fake_previews(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["shot_id"] == shot_id
        return [{"shot_id": shot_id}]

    async def fake_settings(*args: Any, **kwargs: Any) -> FakeSettings:
        return settings

    settings = FakeSettings()
    session = FakeSession()
    monkeypatch.setattr(prompt_approvals, "list_storyboard_prompt_previews", fake_previews)
    monkeypatch.setattr(prompt_approvals, "get_or_create_production_settings", fake_settings)

    updated = await update_storyboard_prompt(
        cast(AsyncSession, session),
        project_id,
        script_id,
        shot_id,
        "  Prompt editado para gerar este quadro.  ",
    )

    assert updated is True
    assert session.committed is True
    assert _storyboard_effective_prompt(settings.metadata_json, script_id, shot_id, "Original") == (
        "Prompt editado para gerar este quadro."
    )


@pytest.mark.asyncio
async def test_selected_storyboard_shots_can_filter_single_shot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script_id = uuid4()
    first_shot = Shot(id=uuid4(), shot_number=1)
    second_shot = Shot(id=uuid4(), shot_number=2)
    scene = Scene(id=uuid4(), scene_number=1)

    async def fake_ordered_shots(*args: Any, **kwargs: Any) -> list[tuple[Shot, Scene]]:
        return [(first_shot, scene), (second_shot, scene)]

    monkeypatch.setattr(storyboard_service, "_ordered_shots_for_script", fake_ordered_shots)

    _all_rows, selected_rows, frame_number_by_shot = await _selected_storyboard_shots(
        cast(AsyncSession, object()),
        project_id,
        script_id,
        shot_id=second_shot.id,
    )

    assert selected_rows == [(second_shot, scene)]
    assert frame_number_by_shot[second_shot.id] == 2


def test_local_storage_file_exists_checks_storage_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    storyboard_dir = storage_root / "openrouter_storyboards"
    storyboard_dir.mkdir(parents=True)
    frame_file = storyboard_dir / "frame.png"
    frame_file.write_bytes(b"image")
    monkeypatch.setattr(
        storyboard_service,
        "get_settings",
        lambda: type("Settings", (), {"local_storage_path": storage_root})(),
    )

    assert _local_storage_file_exists("openrouter_storyboards/frame.png")
    assert not _local_storage_file_exists("openrouter_storyboards/missing.png")


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
        raise AssertionError("planos não devem ser consultados antes da biblioteca visual")

    monkeypatch.setattr(storyboard_service, "ProjectRepository", FakeProjectRepository)
    monkeypatch.setattr(
        storyboard_service,
        "visual_reference_completion_report",
        fake_visual_report,
    )
    monkeypatch.setattr(storyboard_service, "_ordered_shots_for_script", fail_ordered_shots)

    with pytest.raises(ValueError, match="Biblioteca Visual"):
        await generate_storyboard_frames(cast(AsyncSession, FakeSession()), project_id, script.id)


@pytest.mark.asyncio
async def test_generate_storyboard_frames_requires_shots(
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

    async def fake_visual_report(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"complete": True, "missing_categories": [], "missing_views": 0}

    async def fake_ordered_shots(*args: Any, **kwargs: Any) -> list[tuple[Shot, Scene]]:
        return []

    monkeypatch.setattr(storyboard_service, "ProjectRepository", FakeProjectRepository)
    monkeypatch.setattr(
        storyboard_service,
        "visual_reference_completion_report",
        fake_visual_report,
    )
    monkeypatch.setattr(storyboard_service, "_ordered_shots_for_script", fake_ordered_shots)

    with pytest.raises(ValueError, match="Nenhum plano"):
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
