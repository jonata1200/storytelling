"""Regressão da passada global de adjudicação da extração de personagens."""

from typing import Any

from app.visual_bible.script_profiles import (
    _adjudication_inventory,
    _apply_adjudication,
    _character_presence_signals,
)


def test_presence_signals_counts_cues_actions_and_scenes() -> None:
    script = (
        "CENA 1\nINT. CASA - NOITE\n"
        "MÃE ajeita o cabelo.\n"
        "MÃE\nVem jantar!\n"
        "Elias respira fundo.\n"
        "\n"
        "CENA 2\nEXT. RUA - DIA\n"
        "MÃE\nVamos.\n"
        "Elias corre para o portão.\n"
        "Nova Chamada Entrante aparece no visor.\n"
    )
    mae = _character_presence_signals(script, "Mãe")
    elias = _character_presence_signals(script, "Elias")
    nova = _character_presence_signals(script, "Nova Chamada Entrante")

    assert mae["dialogue_cues"] == 2
    assert mae["scene_presence"] == 2
    assert elias["action_mentions"] >= 2
    # Falso personagem real: 1 menção, zero fala, zero segunda cena.
    assert nova["dialogue_cues"] == 0
    assert nova["scene_presence"] <= 1
    assert nova["action_mentions"] <= 1


def test_inventory_compacts_signals_for_llm() -> None:
    script = "CENA 1\nINT. CASA - NOITE\nMÃE\nVem!\nElias corre.\n"
    characters = [{"name": "Mãe", "role": "mae", "evidence_text": ["MÃE"]}]
    inventory = _adjudication_inventory(script, characters)
    assert inventory[0]["name"] == "Mãe"
    assert inventory[0]["dialogue_cues"] == 1
    assert inventory[0]["scene_presence"] == 1


def test_apply_adjudication_excludes_non_characters_with_reason() -> None:
    characters = [
        {"name": "Marina", "role": "protagonista", "evidence_text": ["Marina atende."]},
        {
            "name": "Nova Chamada Entrante",
            "evidence_text": ["NOVA CHAMADA ENTRANTE pisca no visor."],
        },
    ]
    verdict = {
        "exclude": [
            {
                "name": "Nova Chamada Entrante",
                "reason": "rótulo de evento no visor; sem ação, fala ou presença física",
            }
        ],
        "merge": [],
        "low_confidence": [],
    }
    kept, exclusions, low = _apply_adjudication(characters, verdict)
    assert [c["name"] for c in kept] == ["Marina"]
    assert exclusions[0]["name"] == "Nova Chamada Entrante"
    assert "visor" in exclusions[0]["reason"]
    assert low == []


def test_apply_adjudication_merges_aliases_into_survivor() -> None:
    mae = {
        "name": "Mãe",
        "aliases": [],
        "evidence_text": ["MÃE ajeita o cabelo."],
        "scene_numbers": [1],
    }
    mae_do_daniel = {
        "name": "A Mãe Do Daniel",
        "aliases": [],
        "evidence_text": ["A mãe do Daniel chega correndo."],
        "scene_numbers": [3],
    }
    verdict = {
        "exclude": [],
        "merge": [
            {
                "keep": "Mãe",
                "merge_into": ["A Mãe Do Daniel"],
                "reason": "mesma pessoa referida de duas formas",
            }
        ],
        "low_confidence": [],
    }
    kept, exclusions, _low = _apply_adjudication([mae, mae_do_daniel], verdict)
    assert len(kept) == 1
    assert kept[0]["name"] == "Mãe"
    # evidências e cenas do unido migram para o sobrevivente
    assert "A mãe do Daniel chega correndo." in kept[0]["evidence_text"]
    assert 3 in kept[0]["scene_numbers"]
    assert "A Mãe Do Daniel" in kept[0]["aliases"]
    assert exclusions[0]["name"] == "A Mãe Do Daniel"


def test_apply_adjudication_never_erases_whole_cast() -> None:
    characters = [{"name": "Marina", "evidence_text": ["Marina respira."]}]
    verdict: dict[str, Any] = {
        "exclude": [{"name": "Marina", "reason": "alucinação do modelo"}],
        "merge": [],
        "low_confidence": [],
    }
    kept, exclusions, _low = _apply_adjudication(characters, verdict)
    # conservadorismo: veredito que apagaria o elenco inteiro é ignorado
    assert len(kept) == 1
    assert exclusions == []


def test_apply_adjudication_marks_low_confidence_on_character() -> None:
    characters = [{"name": "Vizinho", "evidence_text": ["O vizinho observa."]}]
    verdict = {
        "exclude": [],
        "merge": [],
        "low_confidence": [
            {"name": "Vizinho", "reason": "aparição única sem falas"}
        ],
    }
    kept, _exclusions, low = _apply_adjudication(characters, verdict)
    assert len(kept) == 1
    assert kept[0]["low_confidence"] == {"reason": "aparição única sem falas"}
    assert low == [{"name": "Vizinho", "reason": "aparição única sem falas"}]


def test_apply_adjudication_with_invalid_verdict_keeps_everything() -> None:
    characters = [{"name": "Marina"}]
    kept, exclusions, low = _apply_adjudication(characters, None)
    assert kept == characters
    assert exclusions == []
    assert low == []