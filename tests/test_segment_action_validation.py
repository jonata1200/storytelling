"""Regressões do validador de segmentos contínuos (falsos positivos de terminação)."""

import pytest

import app.video_generation.continuous  # noqa: F401  (quebra o ciclo de import)
from app.video_generation.continuous_planning import (
    continuous_video_segment_validation_errors,
)


class _Segment:
    """Stub mínimo no shape consumido pelo validador."""

    def __init__(self, *, action: str, prompt: str = "Ação concreta e filmável na praça.") -> None:
        self.segment_number = 2
        self.duration_seconds = 8
        self.prompt = prompt
        self.metadata_json = {
            "action": action,
            "continuity": {"continuity_break": False},
        }


@pytest.mark.parametrize(
    "action",
    [
        "Quando ele levanta a tampa do piano, a música para.",
        "A câmera se aproxima das teclas e a melodia para.",
        "ELIAS corre pela praça e para.",
    ],
)
def test_action_ending_in_verb_para_is_not_fragile(action: str) -> None:
    """\"...a música para.\" termina no VERBO parar — não é frase incompleta."""
    segment = _Segment(action=action)
    assert continuous_video_segment_validation_errors(segment) == []


@pytest.mark.parametrize(
    "action",
    [
        "ELIAS corre para o palco e",
        "ELIAS sai para",
        "A câmera avança para",
    ],
)
def test_action_truly_truncated_still_flags(action: str) -> None:
    """Terminação genuinamente truncada continua sendo sinalizada."""
    segment = _Segment(action=action)
    assert "acao principal termina em frase incompleta" in (
        continuous_video_segment_validation_errors(segment)
    )


def test_other_validation_errors_unaffected() -> None:
    segment = _Segment(action="")
    errors = continuous_video_segment_validation_errors(segment)
    assert "acao principal ausente" in errors