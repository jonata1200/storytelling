"""Regressão: roteiro sem planos/câmera + extração sem objetos-fantasma."""

from app.storytelling.script_normalization import (
    FORBIDDEN_CAMERA_RE,
    _remove_forbidden_camera_directions,
    screenplay_validation_errors,
)
from app.visual_bible.script_profiles import (
    _looks_like_non_character_name,
    _script_character_items,
)


def test_validator_rejects_camera_directions() -> None:
    errors = screenplay_validation_errors(
        """
FADE IN:

CENA 01 - INT. ESTACAO DE RADIO - NOITE

PLANO DETALHE: uma PORTA de metal enferrujada. VALTER pressiona a mao.

FADE OUT.
"""
    )
    assert any("plano ou câmera" in error for error in errors)


def test_validator_rejects_camera_subject_phrases() -> None:
    errors = screenplay_validation_errors(
        """
FADE IN:

CENA 01 - INT. ESTACAO DE RADIO - NOITE

A câmera se afasta, revelando o estúdio. VALTER recua.

FADE OUT.
"""
    )
    assert any("plano ou câmera" in error for error in errors)


def test_validator_accepts_script_without_camera_mentions() -> None:
    errors = screenplay_validation_errors(
        """
FADE IN:

CENA 01 - INT. ESTACAO DE RADIO - NOITE

VALTER pressiona a mão contra a porta enferrujada. O rádio crepita.

FADE OUT.
"""
    )
    assert errors == []


def test_camera_word_as_object_is_not_flagged() -> None:
    """'câmera' como OBJETO em cena ("ajusta a câmera do celular") é legítimo."""
    assert FORBIDDEN_CAMERA_RE.search("VALTER ajusta a câmera do celular.") is None


def test_remover_strips_camera_label_lines() -> None:
    cleaned = _remove_forbidden_camera_directions(
        "PLANO DETALHE: uma PORTA enferrujada.\n"
        "VALTER pressiona a mão.\n"
        "PRIMEIRÍSSIMO PLANO no rosto dele.\n"
        "O rádio crepita.\n"
    )
    assert "PLANO DETALHE" not in cleaned
    assert "PRIMEIRÍSSIMO" not in cleaned
    assert "VALTER pressiona a mão." in cleaned
    assert "O rádio crepita." in cleaned


def test_remover_strips_camera_phrases_inside_action() -> None:
    cleaned = _remove_forbidden_camera_directions(
        "VALTER recua. A câmera PERMANECE no carro, e o som desaparece. O rádio emite um bipe.\n"
        "A câmera se afasta, revelando o estúdio. Uma MULHER ajusta os controles.\n"
    )
    assert "câmera" not in cleaned.lower()
    assert "VALTER recua." in cleaned
    assert "O rádio emite um bipe." in cleaned
    assert "Uma MULHER ajusta os controles." in cleaned


def test_technical_labels_are_not_characters() -> None:
    for name in (
        "Gravação",
        "Gravador",
        "Rádio",
        "Telefone",
        "Última Transmissão",
        "Sinal Perdido",
        "Sistema",
    ):
        assert _looks_like_non_character_name(name), name


def test_radio_station_script_yields_only_real_characters() -> None:
    """Caso real (A Última Frequência): GRAVAÇÃO como cue enganava o parser."""
    script = (
        "CENA 01 - INT. ESTAÇÃO DE RÁDIO ABANDONADA - NOITE\n\n"
        "PLANO DETALHE: uma PORTA de metal enferrujada. VALTER pressiona a mão.\n\n"
        "GRAVAÇÃO\n...e foi naquela noite que eu vi algo que nunca consegui explicar.\n\n"
        "VALTER\nIsso não é real.\n\n"
        "VALTER está sentado. Um GRAVADOR está ligado à sua frente. Ele fala:\n\n"
        "MULHER\nQuem está aí?\n"
    )
    names = [item["name"] for item in _script_character_items(script)]
    assert names == ["Valter", "Mulher"]


def test_extraction_prompt_bans_objects_and_technical_cues() -> None:
    from app.visual_bible.script_profile_contracts import extraction_prompt

    prompt = extraction_prompt("CENA 1\nINT. CASA - NOITE", 1, 1, "")
    assert "PESSOA FÍSICA" in prompt
    assert "GRAVAÇÃO" in prompt
    assert "NÃO inclua: objetos" in prompt