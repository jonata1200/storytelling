"""Testes do contexto enriquecido dos prompts de frame e vídeo."""

from types import SimpleNamespace
from uuid import uuid4

from app.generation.shot_generation_spec import ShotGenerationSpec
from app.generation.shot_prompt_compiler import VibesPromptCompiler
from app.storytelling.scene_plan_normalization import (
    _is_character_cue,
    _section_lighting,
    _section_location,
    _shot_visual_composition,
)
from app.video_generation.continuous_frames import (
    _action_is_fragment,
    segment_frame_prompts,
)


def test_transition_markers_and_sluglines_are_not_character_cues() -> None:
    assert _is_character_cue("CORTE PARA:") is False
    assert _is_character_cue("INT. DEPÓSITO ABANDONADO - NOITE") is False
    assert _is_character_cue("FADE IN") is False
    assert _is_character_cue("RAFAEL") is True
    assert _is_character_cue("VOZ GRAVADA") is True


def test_section_location_uses_natural_title_case() -> None:
    assert _section_location("INT. SALA DE SEGURANÇA DO MUSEU - NOITE") == (
        "Sala de Segurança do Museu"
    )
    assert _section_location("EXT. RUA PRINCIPAL - DIA") == "Rua Principal"


def test_section_lighting_extracts_first_light_mention() -> None:
    context = (
        "Close extremo em um relógio de pulso. A luz azulada de MONITORES DE "
        "SEGURANÇA reflete nas mãos de Rafael."
    )
    assert "luz azulada" in _section_lighting(context)


def test_section_lighting_returns_empty_without_mention() -> None:
    assert _section_lighting("Rafael corre para a porta.") == ""


def test_shot_visual_composition_is_specific_not_placeholder() -> None:
    composition = _shot_visual_composition(
        action="Rafael ajusta o controle da câmera.",
        characters=["Rafael", "Lúcia"],
        location="Sala de Segurança do Museu",
        lighting="luz azulada de monitores",
    )
    assert "nestá" not in composition
    assert "baseada nesta cena do roteiro" not in composition
    assert "Rafael" in composition
    assert "Sala de Segurança do Museu" in composition
    assert "luz azulada" in composition


def test_vibes_compiler_omits_large_secondary_cast() -> None:
    def _spec(characters: list[str]) -> ShotGenerationSpec:
        return ShotGenerationSpec(
            shot_id=uuid4(),
            scene_id=uuid4(),
            scene_title="Cena",
            scene_summary="Resumo",
            duration_seconds=8,
            characters=characters,
            action="Rafael ajusta o controle da câmera.",
            emotion="tensão",
            visual_composition="Plano centrado em Rafael",
            camera_movement="estático",
        )

    three_off_cast = VibesPromptCompiler().compile(
        _spec(["Rafael", "Lúcia", "Daniel", "Detetive"])
    )
    assert "também estão em cena" not in three_off_cast.prompt

    one_off_cast = VibesPromptCompiler().compile(_spec(["Rafael", "Lúcia"]))
    assert "Lúcia também está em cena" in one_off_cast.prompt


def test_action_fragment_detector_flags_cue_only_beats() -> None:
    assert _action_is_fragment("DANIEL.") is True
    assert _action_is_fragment("Rafael pega o rádio.") is False
    assert _action_is_fragment("A luz vermelha pisca.") is False


def test_frame_prompt_drops_leading_cue_fragments() -> None:
    segment = SimpleNamespace(
        prompt="fallback",
        metadata_json={
            "storyboard_action": "DANIEL. RAFAEL olha para o painel de controle.",
            "shot_generation_spec": {
                "action": "DANIEL.",
                "scene_context": (
                    "Daniel aparece no vão da porta. Rafael olha para o painel "
                    "de controle e reconhece a voz."
                ),
            },
        },
    )

    prompts = segment_frame_prompts(segment)  # type: ignore[arg-type]

    assert "Mostre o momento inicial em que DANIEL." not in prompts["initial"]
    assert "RAFAEL olha para o painel de controle" in prompts["initial"]


def test_frame_prompt_falls_back_to_scene_context_when_beat_is_only_fragment() -> None:
    segment = SimpleNamespace(
        prompt="fallback",
        metadata_json={
            "storyboard_action": "DANIEL.",
            "shot_generation_spec": {
                "action": "DANIEL.",
                "scene_context": (
                    "Daniel aparece no vão da porta. Rafael olha para o painel "
                    "de controle e reconhece a voz."
                ),
            },
        },
    )

    prompts = segment_frame_prompts(segment)  # type: ignore[arg-type]

    assert "Mostre o momento inicial em que DANIEL." not in prompts["initial"]
    assert "Daniel aparece no vão da porta" in prompts["initial"]