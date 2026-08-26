from app.visual_bible.image_generation import _strip_view_instructions
from app.visual_bible.reference_planning import (
    CHARACTER_META_INSTRUCTION,
    plan_visual_references,
)


def test_strip_view_instructions_removes_character_meta_instruction() -> None:
    base = "Crie a imagem de Ana, deve ter cabelo preto e olhos castanhos."
    final = f"{base} {CHARACTER_META_INSTRUCTION}"

    assert _strip_view_instructions(final, "character") == base


def test_strip_view_instructions_removes_location_establishing_instruction() -> None:
    plan = plan_visual_references("location", __import__("uuid").uuid4(), {
        "canonical_prompt": "Sala antiga com janela lateral."
    })
    final = plan.items[0].prompt

    stripped = _strip_view_instructions(final, "location")

    assert "ambiente inteiro em plano geral" not in stripped
    assert stripped == "Sala antiga com janela lateral."


def test_strip_view_instructions_keeps_user_text_without_known_suffix() -> None:
    custom = "Prompt revisado pelo usuário, corpo inteiro e fundo simples."

    assert _strip_view_instructions(custom, "character") == custom
    assert _strip_view_instructions(custom, "prop") == custom