from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.assets.models import Asset
from app.generation.shot_generation_spec import ShotGenerationSpec
from app.generation.shot_prompt_compiler import VIDEO_PROMPT_MAX_CHARS, VibesPromptCompiler
from app.storytelling.models import Scene, Script, Shot
from app.video_generation import continuous, continuous_generation, continuous_review
from app.video_generation.continuous import build_continuous_video_segment_payloads
from app.video_generation.continuous_frames import segment_frame_prompts
from app.video_generation.continuous_prompting import video_provider_prompt
from app.video_generation.continuous_review import (
    _reset_continuous_video_segment_for_regeneration,
    select_continuous_video_segment_variant,
)
from app.video_generation.models import ContinuousVideoSegment


def test_prompt_optimization_preserves_user_edited_portuguese_prompt() -> None:
    segment = SimpleNamespace(
        review_status="pending",
        prompt="Movimento personalizado pelo usuário.",
        metadata_json={
            "custom_prompt": True,
            "source_text": "A personagem atravessa o corredor.",
        },
    )

    changed = continuous._refresh_auto_segment_prompt(
        segment,  # type: ignore[arg-type]
        force_regenerate=True,
    )

    assert changed is False
    assert segment.prompt == "Movimento personalizado pelo usuário."


def test_prompt_optimization_uses_each_segment_storyboard_action() -> None:
    project_id = uuid4()

    def segment(number: int, storyboard_action: str) -> SimpleNamespace:
        return SimpleNamespace(
            project_id=project_id,
            segment_number=number,
            duration_seconds=8,
            provider="vibes",
            model="vibes",
            review_status="pending",
            prompt="Prompt repetido da cena.",
            generated_video_asset_id=None,
            asset_id=None,
            source_segment_id=None,
            source_video_asset_id=None,
            metadata_json={
                "custom_prompt": False,
                "source_text": "Resumo longo compartilhado por todos os shots.",
                "action": "Resumo longo compartilhado por todos os shots.",
                "storyboard_action": storyboard_action,
            },
        )

    first = segment(1, "Ana abre a porta.")
    second = segment(2, "Caio liga o motor.")

    assert continuous._refresh_auto_segment_prompt(first, force_regenerate=True)  # type: ignore[arg-type]
    assert continuous._refresh_auto_segment_prompt(second, force_regenerate=True)  # type: ignore[arg-type]
    assert "Ana abre a porta" in first.prompt
    assert "Caio liga o motor" in second.prompt
    assert first.prompt != second.prompt


@pytest.mark.asyncio
async def test_video_planning_creates_missing_scenes_and_shots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script = SimpleNamespace(id=uuid4())
    scene = SimpleNamespace(id=uuid4())
    shot = SimpleNamespace(id=uuid4(), scene_id=scene.id)
    query_results = [([], {}), ([scene], {scene.id: [shot]})]
    generated: list[tuple[object, object, object]] = []

    async def fake_project_scenes_and_shots(
        session: object, requested_project_id: object
    ) -> tuple[list[SimpleNamespace], dict[SimpleNamespace, list[SimpleNamespace]]]:
        assert session is fake_session
        assert requested_project_id == project_id
        return query_results.pop(0)

    async def fake_generate_scenes_and_shots(
        session: object, requested_project_id: object, script_id: object
    ) -> list[object]:
        generated.append((session, requested_project_id, script_id))
        return [scene]

    fake_session = object()
    monkeypatch.setattr(continuous, "_project_scenes_and_shots", fake_project_scenes_and_shots)
    monkeypatch.setattr(
        "app.storytelling.scene_service.generate_scenes_and_shots",
        fake_generate_scenes_and_shots,
    )

    scenes, shots_by_scene = await continuous._ensure_project_scenes_and_shots(
        fake_session, project_id, script  # type: ignore[arg-type]
    )

    assert scenes == [scene]
    assert shots_by_scene == {scene.id: [shot]}
    assert generated == [(fake_session, project_id, script.id)]
    assert query_results == []


@pytest.mark.asyncio
async def test_video_planning_reuses_existing_shots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    scene = SimpleNamespace(id=uuid4())
    shot = SimpleNamespace(id=uuid4(), scene_id=scene.id)

    async def fake_project_scenes_and_shots(
        _session: object, _project_id: object
    ) -> tuple[list[object], dict[object, list[object]]]:
        return [scene], {scene.id: [shot]}

    async def unexpected_generation(*_args: object) -> list[object]:
        raise AssertionError("existing Shots must not be regenerated")

    monkeypatch.setattr(continuous, "_project_scenes_and_shots", fake_project_scenes_and_shots)
    monkeypatch.setattr(
        "app.storytelling.scene_service.generate_scenes_and_shots",
        unexpected_generation,
    )

    scenes, shots_by_scene = await continuous._ensure_project_scenes_and_shots(
        object(), project_id, SimpleNamespace(id=uuid4())  # type: ignore[arg-type]
    )

    assert scenes == [scene]
    assert shots_by_scene == {scene.id: [shot]}


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
    assert [item.duration_seconds for item in payloads] == [8, 8]
    assert payloads[0].metadata_json["prompt_compiler_version"] == (
        "vibes_shot_v13_no_camera_no_plans_no_lighting"
    )
    assert payloads[1].metadata_json["continuity_break"] is True
    assert payloads[1].source_frame_asset_id is None
    assert payloads[0].prompt != payloads[1].prompt
    assert "Ana atravessa a praça" in payloads[0].prompt
    assert "Anoitece em outro local" in payloads[1].prompt

    first_frame_prompts = segment_frame_prompts(
        SimpleNamespace(  # type: ignore[arg-type]
            prompt=payloads[0].prompt,
            metadata_json=payloads[0].metadata_json,
        )
    )
    assert "Ana atravessa a praça" in first_frame_prompts["initial"]
    assert "Ana procura abrigo" not in first_frame_prompts["initial"]
    assert first_frame_prompts["initial"].startswith("Crie uma imagem de ")
    assert "Crie um vídeo" not in payloads[0].prompt
    assert "9:16" not in payloads[0].prompt
    assert first_frame_prompts["initial"] != payloads[0].prompt


def test_planning_drops_characters_not_in_visual_bible() -> None:
    # "A Última Mensagem": a decupagem gravou "Voz Distorcida" (efeito sonoro)
    # em shot.payload.characters, mas a Bíblia Visual só tem "Lúcia". O nome
    # estranho ao contexto visual não pode virar "Voz Distorcida também está
    # em cena" no prompt de vídeo.
    script, scene, shots = _story()
    shots[0].payload = {"characters": ["Lúcia", "Voz Distorcida"]}
    payloads = build_continuous_video_segment_payloads(
        project_id=script.project_id,
        script=script,
        scenes=[scene],
        shots_by_scene={scene.id: shots},
        visual_context={"characters": [{"name": "Lúcia"}], "locations": []},
        provider="vibes",
        model="vibes",
    )

    assert "Voz Distorcida" not in payloads[0].prompt
    assert "Lúcia" in payloads[0].prompt


def test_planning_does_not_replace_shot_actions_with_long_shared_scene_summary() -> None:
    script, scene, shots = _story()
    scene.summary = (
        "A tempestade cobre a cidade. As ruas estão vazias. "
        "A energia falha. Sirenes ecoam ao longe."
    )

    payloads = build_continuous_video_segment_payloads(
        project_id=script.project_id,
        script=script,
        scenes=[scene],
        shots_by_scene={scene.id: shots},
        visual_context={"characters": [{"name": "Ana"}], "locations": []},
        provider="vibes",
        model="vibes",
    )

    assert payloads[0].metadata_json["action"] == "Ana atravessa a praça."
    assert payloads[1].metadata_json["action"] == "Anoitece em outro local."
    assert payloads[0].prompt != payloads[1].prompt


def test_planning_deduplicates_entity_names_case_insensitively() -> None:
    script, scene, shots = _story()
    shots[0].payload = {**shots[0].payload, "location": "PRAÇA"}

    payload = build_continuous_video_segment_payloads(
        project_id=script.project_id,
        script=script,
        scenes=[scene],
        shots_by_scene={scene.id: shots},
        visual_context={
            "characters": [{"name": "Ana"}],
            "locations": [{"name": "Praça"}],
        },
        provider="vibes",
        model="vibes",
    )[0]

    assert payload.metadata_json["locations"] == ["Praça"]


def test_planning_repairs_legacy_fragmented_actions_with_scene_context() -> None:
    script, scene, shots = _story()
    shots[0].action = "Ana para diante de"
    shots[1].action = "uma porta metálica."

    payloads = build_continuous_video_segment_payloads(
        project_id=script.project_id,
        script=script,
        scenes=[scene],
        shots_by_scene={scene.id: shots},
        visual_context={"characters": [{"name": "Ana"}], "locations": []},
        provider="vibes",
        model="vibes",
    )

    for payload in payloads:
        assert payload.metadata_json["action"] == "Ana para diante de uma porta metálica."
        spec = payload.metadata_json["shot_generation_spec"]
        assert "Ana para diante de uma porta metálica." in spec["scene_context"]
        assert spec["character_states"]["Ana"]["continuity_notes"]
        assert payload.duration_seconds == 8


def test_vibes_compiler_describes_only_action_and_essential_context() -> None:
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
    # v12: somente ação/contexto (+ ajuste de rejeição). Sem luz aqui (spec sem
    # lighting), sem enquadramento/planos e sem câmera traduzida.
    assert "Ana entrega a chave a Caio" in compiled.prompt
    assert "Iluminação" not in compiled.prompt  # spec sem lighting definido
    assert "Enquadramento" not in compiled.prompt
    assert "câmera" not in compiled.prompt.casefold()
    assert "dolly" not in compiled.prompt.casefold()
    assert "atmosfera" not in compiled.prompt.casefold()
    assert "manter a chave visível" in compiled.prompt
    assert "Crie um vídeo" not in compiled.prompt
    assert "8 segundos" not in compiled.prompt
    assert "9:16" not in compiled.prompt
    assert "casaco azul" not in compiled.prompt
    assert "a partir do frame inicial" not in compiled.prompt
    assert "legendas" not in compiled.prompt
    assert "anatomia" not in compiled.prompt
    assert "Scene context" not in compiled.prompt
    assert "Create one continuous" not in compiled.prompt
    assert "Revision direction" not in compiled.prompt
    assert len(compiled.prompt) <= VIDEO_PROMPT_MAX_CHARS


def test_video_provider_prompt_caps_oversized_custom_prompt() -> None:
    prompt = "Clara atravessa a oficina e liga o motor antigo. " * 80

    provider_prompt = video_provider_prompt(prompt, {"continuity_break": False})

    assert provider_prompt.startswith("Clara atravessa a oficina")
    assert len(provider_prompt) <= VIDEO_PROMPT_MAX_CHARS
    assert "Preserve identidades" not in provider_prompt
    assert "9:16" not in provider_prompt


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
        external_operation_id="external-old",
        metadata_json={
            "review_note": "corrigir posição",
            "video_job_id": "external-old",
            "video_polling_url": "https://provider.invalid/jobs/external-old",
        },
    )
    _reset_continuous_video_segment_for_regeneration(segment, reason="shot_regeneration")
    assert segment.metadata_json["variants"][0]["asset_id"] == str(old_asset_id)
    assert segment.generated_video_asset_id is None
    assert segment.external_operation_id is None
    assert "video_job_id" not in segment.metadata_json
    selected = await select_continuous_video_segment_variant(
        _VariantSession(segment),  # type: ignore[arg-type]
        project_id,
        segment.id,
        old_asset_id,
    )
    assert selected is segment
    assert segment.generated_video_asset_id == old_asset_id
    assert segment.review_status == "ready"


@pytest.mark.asyncio
async def test_selecting_variant_extracts_and_propagates_continuity_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    variant_id = uuid4()
    extracted_frame_id = uuid4()
    first = ContinuousVideoSegment(
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
        idempotency_key="first",
        review_status="ready",
        metadata_json={"variants": [{"asset_id": str(variant_id), "variant_number": 1}]},
    )
    second = ContinuousVideoSegment(
        id=uuid4(),
        project_id=project_id,
        shot_id=uuid4(),
        segment_number=2,
        title="Shot 2",
        prompt="prompt",
        duration_seconds=5,
        provider="vibes",
        model="vibes",
        request_fingerprint="b" * 64,
        idempotency_key="second",
        review_status="pending",
        metadata_json={},
    )
    variant_asset = SimpleNamespace(id=variant_id, storage_uri="generated/option-1.mp4")

    class Session:
        async def get(self, model: object, identity: object) -> Any:
            if model is ContinuousVideoSegment:
                return first if identity == first.id else second
            if model is Asset:
                return variant_asset
            return None

        async def flush(self) -> None:
            return None

    async def fake_list(_session: object, _project_id: object) -> list[ContinuousVideoSegment]:
        return [first, second]

    async def fake_extract(*args: object, **kwargs: object) -> object:
        return extracted_frame_id

    monkeypatch.setattr(continuous_review, "list_continuous_video_segments", fake_list)
    monkeypatch.setattr(
        continuous_review,
        "resolve_storage_path",
        lambda _uri: Path("generated/option-1.mp4"),
    )
    monkeypatch.setattr(continuous_generation, "_extract_last_frame_from_video", fake_extract)

    selected = await select_continuous_video_segment_variant(
        Session(),  # type: ignore[arg-type]
        project_id,
        first.id,
        variant_id,
    )

    assert selected is first
    assert first.final_frame_asset_id == extracted_frame_id
    assert first.metadata_json["awaiting_variant_selection"] is False
    assert second.source_frame_asset_id == extracted_frame_id
    assert second.metadata_json["continuity_source_variant_asset_id"] == str(variant_id)


def test_migration_keeps_shot_nullable_and_backfill_conservative() -> None:
    source = Path("alembic/versions/202608260034_shot_centered_video_segments.py").read_text(
        encoding="utf-8"
    )
    assert 'sa.Column("shot_id", sa.Uuid(), nullable=True)' in source
    assert "count(*)" in source
    assert "jsonb_array_length" in source
