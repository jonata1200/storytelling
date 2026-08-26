from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.generation.shot_generation_spec import ShotGenerationSpec
from app.generation.shot_prompt_compiler import VibesPromptCompiler
from app.storytelling.models import Scene, Script, Shot
from app.video_generation.continuous import build_continuous_video_segment_payloads
from app.video_generation.continuous_review import (
    _reset_continuous_video_segment_for_regeneration,
    select_continuous_video_segment_variant,
)
from app.video_generation.finalization import assembly_gaps, order_segments_for_assembly
from app.video_generation.models import ContinuousVideoSegment


def _story() -> tuple[Script, Scene, list[Shot]]:
    project_id = uuid4()
    script = Script(
        id=uuid4(),
        project_id=project_id,
        artifact_id=uuid4(),
        story_idea_id=uuid4(),
        title="História",
        language="pt-BR",
        target_duration_seconds=10,
        word_count=10,
        content="Ana atravessa a praça.",
    )
    scene = Scene(
        id=uuid4(),
        project_id=project_id,
        artifact_id=uuid4(),
        script_id=script.id,
        scene_number=1,
        title="Praça",
        summary="Ana procura abrigo.",
        duration_seconds=10,
        payload={},
    )
    shots = [
        Shot(
            id=uuid4(),
            project_id=project_id,
            artifact_id=uuid4(),
            scene_id=scene.id,
            shot_number=number,
            duration_seconds=5,
            narration_text="",
            dialogue_text="",
            action=action,
            emotion="tensão",
            visual_composition="plano médio",
            camera_movement="travelling lateral",
            generation_type="TEXT_TO_VIDEO",
            payload={"continuity_break": number == 2, "characters": ["Ana"]},
        )
        for number, action in [(1, "Ana atravessa a praça"), (2, "Anoitece em outro local")]
    ]
    return script, scene, shots


def test_planning_creates_one_segment_per_shot_and_auditable_spec() -> None:
    script, scene, shots = _story()
    payloads = build_continuous_video_segment_payloads(
        project_id=script.project_id,
        script=script,
        scenes=[scene],
        shots_by_scene={scene.id: shots},
        visual_context={"characters": [{"name": "Ana"}], "locations": []},
        provider="vibes",
        model="vibes",
    )
    assert [item.shot_id for item in payloads] == [shot.id for shot in shots]
    assert [item.duration_seconds for item in payloads] == [5, 5]
    assert payloads[0].metadata_json["prompt_compiler_version"] == "vibes_shot_v1"
    assert payloads[1].metadata_json["continuity_break"] is True
    assert payloads[1].source_frame_asset_id is None


def test_vibes_compiler_uses_state_and_explicit_continuity() -> None:
    spec = ShotGenerationSpec(
        shot_id=uuid4(),
        scene_id=uuid4(),
        scene_title="Corredor",
        scene_summary="A fuga continua",
        duration_seconds=5,
        characters=["Ana", "Caio"],
        action="Ana entrega a chave a Caio",
        emotion="urgência",
        visual_composition="Ana à esquerda, Caio à direita",
        camera_movement="dolly in",
        character_states={
            "Ana": {"outfit": "casaco azul", "carried_props": ["chave"]},
        },
        continuity={"stable_elements": ["chave na mão direita"]},
        visual_references=["approved-reference"],
        ingredient_ids=["ingredient-ana"],
        previous_frame_reference="frame.jpg",
    )
    compiled = VibesPromptCompiler().compile(spec, rejection_note="manter a chave visível")
    assert "Primary action" in compiled.prompt
    assert "dolly in" in compiled.prompt
    assert "casaco azul" in compiled.prompt
    assert "previous frame" in compiled.prompt
    assert "manter a chave visível" in compiled.prompt


class _VariantSession:
    def __init__(self, segment: ContinuousVideoSegment) -> None:
        self.segment = segment

    async def get(self, model: object, identity: object) -> Any:
        return self.segment

    async def flush(self) -> None:
        return None


async def test_single_shot_regeneration_preserves_and_selects_variant() -> None:
    project_id = uuid4()
    old_asset_id = uuid4()
    segment = ContinuousVideoSegment(
        id=uuid4(),
        project_id=project_id,
        shot_id=uuid4(),
        segment_number=1,
        title="Shot 1",
        prompt="prompt",
        duration_seconds=5,
        provider="vibes",
        model="vibes",
        request_fingerprint="a" * 64,
        idempotency_key="key",
        review_status="rejected",
        asset_id=old_asset_id,
        generated_video_asset_id=old_asset_id,
        metadata_json={"review_note": "corrigir posição"},
    )
    _reset_continuous_video_segment_for_regeneration(segment, reason="shot_regeneration")
    assert segment.metadata_json["variants"][0]["asset_id"] == str(old_asset_id)
    selected = await select_continuous_video_segment_variant(
        _VariantSession(segment),
        project_id,
        segment.id,
        old_asset_id,  # type: ignore[arg-type]
    )
    assert selected is segment
    assert segment.generated_video_asset_id == old_asset_id
    assert segment.review_status == "ready"


async def test_assembly_orders_by_scene_and_shot() -> None:
    scene_one = SimpleNamespace(id=uuid4(), scene_number=1)
    scene_two = SimpleNamespace(id=uuid4(), scene_number=2)
    shot_a = SimpleNamespace(id=uuid4(), scene_id=scene_two.id, shot_number=1)
    shot_b = SimpleNamespace(id=uuid4(), scene_id=scene_one.id, shot_number=2)
    first = SimpleNamespace(id=uuid4(), shot_id=shot_a.id, segment_number=1)
    second = SimpleNamespace(id=uuid4(), shot_id=shot_b.id, segment_number=2)
    objects = {
        shot_a.id: shot_a,
        shot_b.id: shot_b,
        scene_one.id: scene_one,
        scene_two.id: scene_two,
    }

    class Session:
        async def get(self, model: object, identity: object) -> Any:
            return objects[identity]

    ordered = await order_segments_for_assembly(Session(), [first, second])  # type: ignore[arg-type,list-item]
    assert ordered == [second, first]


def test_assembly_reports_unapproved_shot_gap() -> None:
    segment = SimpleNamespace(
        shot_id=uuid4(),
        segment_number=3,
        review_status="rejected",
        generated_video_asset_id=uuid4(),
        asset_id=None,
        metadata_json={},
    )
    assert "sem clip aprovado" in assembly_gaps([segment])[0]  # type: ignore[list-item]


def test_migration_keeps_shot_nullable_and_backfill_conservative() -> None:
    source = Path("alembic/versions/202608260034_shot_centered_video_segments.py").read_text(
        encoding="utf-8"
    )
    assert 'sa.Column("shot_id", sa.Uuid(), nullable=True)' in source
    assert "count(*)" in source
    assert "jsonb_array_length" in source
