"""Regressões: camera_movement vazio é valor válido na decupagem (vibes_shot_v11)."""

import pytest

from app.generation.shot_generation_spec import ShotGenerationSpec
from app.generation.shot_prompt_compiler import GENERIC_CAMERA_MOVEMENTS, VibesPromptCompiler
from app.storytelling.normalization import (
    GenerationOutputError,
    _bounded_required_str,
    _bounded_str_or_empty,
    normalize_scene_plan_payload,
)
from app.storytelling.scene_plan_normalization import scene_plan_payload_from_script_content

_SCRIPT = """CENA 01
INT. OFICINA - NOITE

Lia abre a porta. Ela acende a luz. Um ruído vem do armário. Lia se aproxima.
"""


def _spec(**overrides: object) -> ShotGenerationSpec:
    defaults: dict[str, object] = {
        "shot_id": "00000000-0000-0000-0000-000000000001",
        "scene_id": "00000000-0000-0000-0000-000000000002",
        "scene_title": "Oficina",
        "scene_summary": "Lia abre a porta.",
        "scene_context": "Oficina à noite, luz fraca.",
        "continuity_state": "",
        "duration_seconds": 8.0,
        "characters": ["Lia"],
        "location": "Oficina",
        "props": [],
        "action": "Lia abre a porta no escuro.",
        "emotion": "tensão",
        "visual_composition": "Plano médio vertical em Lia, dentro da oficina.",
        "camera_movement": "",
        "lighting": "luz fraca de lâmpada de trabalho",
        "character_states": {},
        "continuity": {},
    }
    defaults.update(overrides)
    return ShotGenerationSpec(**defaults)


def test_bounded_str_or_empty_accepts_missing_and_empty() -> None:
    assert _bounded_str_or_empty({"camera_movement": ""}, "camera_movement", "shot", 120) == ""
    assert _bounded_str_or_empty({}, "camera_movement", "shot", 120) == ""
    assert _bounded_str_or_empty({"camera_movement": None}, "camera_movement", "shot", 120) == ""
    long_value = "Travelling lateral acompanha Lia da porta até o armário com zoom" * 3
    truncated = long_value[:117].rstrip() + "..."
    bounded = _bounded_str_or_empty({"camera_movement": long_value}, "camera_movement", "shot", 120)
    assert bounded == truncated


def test_bounded_str_or_empty_truncates_like_required_variant() -> None:
    value = "Camera em travelling lateral com zoom suave e muito detalhe"
    assert _bounded_str_or_empty({"camera_movement": value}, "camera_movement", "shot", 24) == (
        "Camera em travelling..."
    )


def test_local_scene_plan_emits_empty_camera_movement() -> None:
    """Decupagem determinística emite vazio de propósito desde v11."""
    payload = scene_plan_payload_from_script_content(_SCRIPT, 40)

    assert payload is not None
    shots = [shot for scene in payload["scenes"] for shot in scene["shots"]]
    assert shots
    assert all(shot["camera_movement"] == "" for shot in shots)


def test_normalize_scene_plan_keeps_missing_camera_movement_empty() -> None:
    """Plano cru do LLM sem o campo não deve receber placeholder de câmera."""
    payload = normalize_scene_plan_payload(
        {
            "scenes": [
                {
                    "scene_number": 1,
      "title": "Oficina",
                    "summary": "Lia abre a porta.",
                    "duration_seconds": 8,
                    "shots": [
                        {
                            "shot_number": 1,
                            "duration_seconds": 8,
                            "narration_text": "Lia abre a porta.",
                            "dialogue_text": "",
                            "action": "Lia abre a porta no escuro.",
                            "emotion": "tensão",
                            "visual_composition": "Plano médio vertical.",
                            "generation_type": "TEXT_TO_VIDEO",
                        }
                    ],
                }
            ]
        },
        8,
    )

    assert payload["scenes"][0]["shots"][0]["camera_movement"] == ""


def test_shot_pipeline_accepts_empty_camera_movement() -> None:
    """Spec compila com camera_movement vazio — a ponte não falha."""
    spec = _spec(camera_movement="")
    compiled = VibesPromptCompiler().compile(spec)

    assert spec.camera_movement == ""
    assert "A câmera" not in compiled.prompt


def test_generic_camera_movements_include_legacy_setdefault_placeholder() -> None:
    """Placeholder antigo do setdefault é ruído igual ao da v10 — linha omitida."""
    assert "movimento suave e realista" in GENERIC_CAMERA_MOVEMENTS

    spec = _spec(camera_movement="movimento suave e realista")
    compiled = VibesPromptCompiler().compile(spec)

    assert "A câmera" not in compiled.prompt


@pytest.mark.parametrize("field", ["camera_movement", "action", "visual_composition"])
def test_bounded_required_str_still_rejects_empty_for_required_fields(field: str) -> None:
    """Campos obrigatórios continuam obrigatórios — só camera_movement mudou."""
    with pytest.raises(GenerationOutputError, match="empty field"):
        _bounded_required_str({field: "  "}, field, "shot", 120)