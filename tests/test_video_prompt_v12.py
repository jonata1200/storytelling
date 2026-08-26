"""Regressões v12: prompts de vídeo sem câmera/planos + extensão real do frame."""

import pytest

import app.video_generation.continuous  # noqa: F401  (quebra o ciclo de import)
from app.generation.shot_prompt_compiler import strip_camera_directions
from app.video_generation.continuous_prompting import concise_video_prompt
from app.video_generation.continuous_sources import normalize_segment_action

_META_SPEC = {
    "shot_id": "00000000-0000-0000-0000-000000000001",
    "scene_id": "00000000-0000-0000-0000-000000000002",
    "scene_title": "Praça Central",
    "scene_summary": "O piano toca sozinho",
    "scene_context": "Praça ao entardecer.",
    "continuity_state": "",
    "duration_seconds": 8.0,
    "characters": ["Elias"],
    "location": "Praça Central",
    "props": [],
    "action": "Elias se aproxima do piano",
    "emotion": "desconfiança",
    "visual_composition": "Plano centrado em Elias",
    "camera_movement": "",
    "lighting": "luz de entardecer",
    "character_states": {},
    "continuity": {},
}


def test_strip_camera_directions_drops_camera_subject_sentence() -> None:
    action = (
        "A câmera se aproxima em *slow motion*: as teclas do piano começam a se mover "
        "SOZINHAS, tocando uma melodia clássica distorcida. ELIAS entra no quadro, "
        "atraído pelo som. Quando ele levanta a tampa do piano, a música para."
    )

    cleaned = strip_camera_directions(action)

    assert cleaned.startswith("ELIAS entra no quadro")
    assert "câmera" not in cleaned.casefold()
    assert "slow motion" not in cleaned.casefold()
    assert "a música para." in cleaned


def test_strip_camera_directions_keeps_object_camera_sentence() -> None:
    """Câmera como OBJETO da cena ("ajusta a câmera") não é direção — mantém."""
    action = "ELIAS ajusta a câmera do celular antes de filmar a praça."

    assert strip_camera_directions(action) == action


def test_strip_camera_directions_never_returns_empty() -> None:
    assert strip_camera_directions("A câmera gira.") == "A câmera gira."


def test_normalize_segment_action_strips_camera_phrases() -> None:
    action = normalize_segment_action(
        "A câmera se aproxima devagar. ELIAS corre pela praça"
    )

    assert action == "ELIAS corre pela praça."


def test_concise_video_prompt_has_no_camera_or_plans() -> None:
    prompt = concise_video_prompt(
        "A câmera se aproxima. ELIAS olha ao redor, desconfiado.",
        {"shot_generation_spec": dict(_META_SPEC)},
    )

    lowered = prompt.casefold()
    assert "câmera" not in lowered
    assert "enquadramento" not in lowered
    assert "plano " not in lowered
    assert "ELIAS olha ao redor" in prompt


def test_meta_instruction_camera_values_stay_out_of_prompt() -> None:
    spec = {**_META_SPEC, "camera_movement": "dolly in", "visual_composition": "Plano médio"}

    prompt = concise_video_prompt("ELIAS entrega a chave.", {"shot_generation_spec": spec})

    lowered = prompt.casefold()
    assert "câmera" not in lowered
    assert "dolly" not in lowered
    assert "plano" not in lowered


@pytest.mark.parametrize(
    ("signature", "expected"),
    [
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", ".webp"),
        (b"\x89PNG\r\n\x1a\n", ".png"),
        (b"\xff\xd8\xff\xe0", ".jpg"),
        (b"GIF89a", ".gif"),
    ],
)
def test_image_extension_from_signature(signature: bytes, expected: str) -> None:
    """Lógica pura da bridge validada por extração regex (padrão da skill)."""
    import re
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    bridge = (repo / "scripts" / "meta_browser_bridge.mjs").read_text(encoding="utf-8")
    match = re.search(
        r"function imageExtensionFromSignature\(buffer\) \{.*?return null;\n\}",
        bridge,
        re.S,
    )
    assert match, "imageExtensionFromSignature desapareceu da bridge"

    # Executa a lógica extraída contra cada assinatura via Buffer real
    script = (
        "const fn = (function(){\n"
        "return function imageExtensionFromSignature(buffer) {\n"
        + match.group(0).split("{", 1)[1].rsplit("}", 1)[0]
        + "\n};\n})();\n"
        f"const buf = Buffer.from({list(signature)!r});\n"
        "console.log(fn(buf));"
    )
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert result.stdout.strip() == expected