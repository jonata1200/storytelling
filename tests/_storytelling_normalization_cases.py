# ruff: noqa: F401
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.storytelling import service as storytelling_service
from app.storytelling.models import StoryIdea
from app.storytelling.script_contracts import _idea_script_contract
from app.storytelling.service import (
    GenerationOutputError,
    _bounded_required_str,
    _fallback_script_content_from_bible,
    _fallback_script_content_from_idea,
    _shot_narration_text,
    _story_idea_db_text,
    coerce_duration_minutes,
    expected_script_scene_count,
    normalize_scene_plan_payload,
    normalize_scene_plan_payload_from_script,
    normalize_script_payload,
    normalize_story_bible_payload,
    normalize_story_idea_payload,
    scene_plan_payload_from_script_content,
    screenplay_validation_errors,
    story_idea_validation_errors,
)
from app.ui import pages
from app.ui.pages import DEFAULT_STORY_DURATION_MINUTES, _asset_url, _compact_project_title
from app.ui.routes import home_pages
from app.ui.workspace import storyboard_video_area
from app.video_generation.durations import VIDEO_CLIP_ALLOWED_SECONDS


def test_idea_lab_duration_and_count_options_match_generation_controls() -> None:
    assert pages.STORY_DURATION_OPTIONS == [2, 4, 6, 8, 10]
    assert pages.IDEA_COUNT_OPTIONS == [3, 6, 9]
    assert "Documentário" not in pages.IDEA_GENRES
    assert "Histórias familiares emocionantes" not in pages.IDEA_GENRES


def test_idea_generation_progress_reports_slow_first_response() -> None:
    detail = home_pages._idea_generation_progress_detail(0, 3, elapsed_seconds=60)

    assert "demorando mais que o normal" in detail
    assert "Falta criar: 3 ideia(s)." in detail


def test_story_idea_payload_is_normalized_for_pipeline() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "A ultima mensagem",
            "premise": "Uma filha recebe uma mensagem atrasada do pai.",
        }
    )

    assert payload["title"] == "A ultima mensagem"
    assert payload["hook"] == "Uma filha recebe uma mensagem atrasada do pai."
    assert payload["duration_minutes"] == 5
    assert payload["retention_potential"] == 75
    assert payload["production_complexity"] == 35
    assert DEFAULT_STORY_DURATION_MINUTES == 5.0


def test_story_idea_payload_preserves_selected_duration() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "O relogio parado",
            "premise": "Uma familia revive o mesmo minuto ate dizer a verdade.",
            "duration_minutes": 7,
        }
    )

    assert payload["duration_minutes"] == 7
    assert coerce_duration_minutes("1") == 2.0
    assert coerce_duration_minutes("2") == 2.0
    assert coerce_duration_minutes("20") == 20.0
    assert coerce_duration_minutes("30") == 25.0


def test_story_idea_payload_coerces_non_integer_scores() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "A promessa",
            "premise": "Uma promessa esquecida volta no pior dia possível.",
            "retention_potential": "alto",
            "cliche_risk": "15%",
            "production_complexity": "8/10",
        }
    )

    assert payload["retention_potential"] == 80
    assert payload["cliche_risk"] == 15
    assert payload["production_complexity"] == 80


def test_story_idea_payload_defaults_unknown_scores() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "A carta",
            "premise": "Uma carta chega tarde demais.",
            "retention_potential": "muito promissor",
            "cliche_risk": None,
            "production_complexity": "simples",
        }
    )

    assert payload["retention_potential"] == 75
    assert payload["cliche_risk"] == 25
    assert payload["production_complexity"] == 35


def test_story_idea_validation_requires_narrative_engine_fields() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "A carta",
            "genre": "Drama",
            "primary_emotion": "Saudade",
            "hook": "Uma carta antiga aparece em uma mesa vazia.",
            "premise": "Uma filha precisa decidir se abre a ultima carta da mae.",
            "protagonist": "Lia, uma professora que evita despedidas",
            "retention_potential": 82,
            "cliche_risk": 18,
            "production_complexity": 30,
        }
    )

    errors = story_idea_validation_errors(payload)

    assert "campo obrigatório vazio: conflict" in errors
    assert "campo obrigatório vazio: twist" in errors
    assert "campo obrigatório vazio: payoff" in errors
    assert "campo obrigatório vazio: resolution" in errors


def test_story_idea_validation_accepts_complete_payload() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "A carta",
            "genre": "Drama",
            "primary_emotion": "Saudade",
            "hook": "Uma carta antiga aparece em uma mesa vazia.",
            "premise": "Uma filha precisa decidir se abre a ultima carta da mae.",
            "protagonist": "Lia, uma professora que evita despedidas",
            "conflict": "Abrir a carta pode destruir a imagem que ela guarda da mae.",
            "obstacles": ["culpa", "silencio familiar"],
            "stakes": "Perder a ultima chance de entender a propria historia.",
            "twist": "A carta foi escrita pela filha quando crianca.",
            "climax": "Lia le a carta diante da familia reunida.",
            "payoff": "Ela entende que a despedida era tambem uma permissão para viver.",
            "resolution": "Lia guarda a carta em um album aberto.",
            "retention_potential": 82,
            "cliche_risk": 18,
            "production_complexity": 30,
        }
    )

    assert story_idea_validation_errors(payload) == []


def test_story_idea_validation_rejects_non_portuguese_generation() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "The Glass Bridge",
            "genre": "Drama",
            "primary_emotion": "Courage",
            "hook": "A woman must cross the bridge she promised to destroy.",
            "premise": "After an old accident, she returns to the city to face the truth.",
            "protagonist": "Marta, a bridge engineer",
            "conflict": "Signing the report reopens the secret behind the accident.",
            "obstacles": ["hostile neighbors", "missing evidence"],
            "stakes": "The town may lose its only evacuation route.",
            "twist": "The original mistake was not hers, but she protected the culprit.",
            "climax": "Marta crosses the bridge during the evacuation.",
            "payoff": "She chooses truth over reputation.",
            "resolution": "The bridge is repaired and named after the victims.",
            "retention_potential": 78,
            "cliche_risk": 22,
            "production_complexity": 40,
        }
    )

    errors = story_idea_validation_errors(payload)

    assert any("portugues do Brasil" in error for error in errors)


def test_story_bible_payload_is_normalized_to_structured_model() -> None:
    payload = normalize_story_bible_payload(
        {
            "title": "O ultimo almoco",
            "logline": "Uma avo prepara uma receita antes de revelar um segredo.",
            "characters": [
                {
                    "eyes": "olhos castanhos atentos",
                    "hair": "coque baixo branco",
                    "role": "protagonista",
                    "base_outfit": {
                        "peca_principal": "vestido azul",
                        "textura": "algodao gasto",
                    },
                },
                "palette_caracteristicas_visuais_para_o_personagem",
                "arc_aceita_dividir_o_legado",
            ],
        },
        {"protagonist": "Dona Lourdes"},
        cast(
            Any,
            SimpleNamespace(
                theme="memória familiar",
                genre="drama",
                audience="adultos",
                primary_emotion="saudade",
            ),
        ),
    )

    assert payload["theme"] == "memória familiar"
    assert payload["export_profile"] == {
        "aspect_ratio": "9:16",
        "resolution": "1080x1920",
        "language": "pt-BR",
    }
    assert len(payload["characters"]) == 1
    assert payload["characters"][0]["name"] == "Dona Lourdes"
    assert payload["characters"][0]["base_outfit"]["main_piece"] == "vestido azul"
    assert payload["locations"][0]["name"] == "Local principal"
    assert payload["props"][0]["name"] == "Objeto de revelacao"
    assert "script_contract" in payload
    assert "visual_contract" in payload
    assert payload["quality_report"]["completeness_score"] < 80


def test_story_bible_payload_accepts_named_location_and_prop_maps() -> None:
    payload = normalize_story_bible_payload(
        {
            "title": "A carta",
            "logline": "Uma carta muda uma familia.",
            "locais": {"sala_de_estar": {"lighting": "luz quente"}},
            "objetos": {"carta_azul": {"material": "papel envelhecido"}},
        }
    )

    assert payload["locations"][0]["name"] == "Sala De Estar"
    assert payload["locations"][0]["lighting"] == "luz quente"
    assert payload["props"][0]["name"] == "Carta Azul"
    assert payload["props"][0]["material"] == "papel envelhecido"


def test_story_idea_payload_requires_title() -> None:
    with pytest.raises(GenerationOutputError, match="title"):
        normalize_story_idea_payload({"premise": "sem titulo"})


def test_script_payload_accepts_common_ai_field_names() -> None:
    payload = normalize_script_payload(
        {
            "titulo": "ignorado",
            "roteiro": "Cena 1: Uma carta chega tarde demais.",
            "word_count": "8",
        },
        default_title="A carta azul",
        language="pt-BR",
        target_duration_seconds=420,
    )

    assert payload["title"] == "A carta azul"
    assert payload["language"] == "pt-BR"
    assert payload["target_duration_seconds"] == 420
    assert payload["word_count"] > 8
    assert "FADE IN:" in payload["content"]
    assert "CENA 01" in payload["content"]
    assert "INT. AMBIENTE PRINCIPAL - DIA" in payload["content"]
    assert "INT. CENA 1 - DIA" not in payload["content"]
    assert "Cena 1: Uma carta chega tarde demais." in payload["content"]


def test_script_payload_preserves_briefing_duration_over_model_output() -> None:
    payload = normalize_script_payload(
        {
            "title": "A carta azul",
            "target_duration_seconds": 999,
            "content": "Cena 1: Uma carta chega tarde demais.",
        },
        default_title="A carta azul",
        language="pt-BR",
        target_duration_seconds=420,
    )

    assert payload["target_duration_seconds"] == 420


def test_script_payload_unwraps_serialized_json_content() -> None:
    serialized_script = (
        '{"title":"O Enquadramento","language":"pt-BR",'
        '"target_duration_seconds":300,"word_count":650,'
        '"content":"FADE IN:\\n\\nCENA 01\\nINT. LABORATORIO DE FOTOGRAFIA - NOITE\\n\\n'
        'CLARA observa fotografias de cenas de crime.\\n\\nCLARA\\n'
        'Não é possível.\\n\\nFADE OUT."}'
    )
    nested_content = (
        "FADE IN:\n\nCENA 01\nINT. AMBIENTE PRINCIPAL - DIA\n\n"
        f"{serialized_script}\n\nFADE OUT."
    )

    payload = normalize_script_payload(
        {
            "title": "O Enquadramento",
            "content": nested_content,
        },
        default_title="O Enquadramento",
        language="pt-BR",
        target_duration_seconds=300,
    )

    assert payload["content"].startswith("FADE IN:")
    assert "CENA 01 - INT. LABORATORIO DE FOTOGRAFIA - NOITE" in payload["content"]
    assert "CLARA observa fotografias" in payload["content"]
    assert '{"title"' not in payload["content"]
    assert "\\n" not in payload["content"]


def test_script_payload_unwraps_malformed_embedded_json_content() -> None:
    nested_content = (
        'FADE IN:\n\nCENA 01\nINT. AMBIENTE PRINCIPAL - DIA\n\n{ "title": '
        '"O Enquadramento", "language": "pt-BR", "content": "FADE IN:\\n\\n'
        'CENA 01\\nINT. LABORATORIO DE FOTOGRAFIA - NOITE\\n\\nCLARA analisa '
        'uma fotografia.\\n\\nCLARA\\nIsso não fecha.\n\nFADE OUT.'
    )

    payload = normalize_script_payload(
        {
            "title": "O Enquadramento",
            "content": nested_content,
        },
        default_title="O Enquadramento",
        language="pt-BR",
        target_duration_seconds=300,
    )

    assert "CENA 01 - INT. LABORATORIO DE FOTOGRAFIA - NOITE" in payload["content"]
    assert "CLARA analisa uma fotografia." in payload["content"]
    assert '{"title"' not in payload["content"]
    assert "\\n" not in payload["content"]


def test_script_payload_adds_scene_markers_to_screenplay_without_cena_labels() -> None:
    payload = normalize_script_payload(
        {
            "title": "A carta azul",
            "content": """
TITULO: A carta azul

FADE IN:

INT. SALA - DIA

Clara encontra uma carta azul sobre a mesa e percebe que a mensagem chegou tarde.

EXT. QUINTAL - NOITE

Clara encara a janela acesa e decide contar a verdade antes do amanhecer.

FADE OUT.
""",
        },
        default_title="A carta azul",
        language="pt-BR",
        target_duration_seconds=420,
    )

    assert "CENA 01 - INT. SALA - DIA" in payload["content"]
    assert "CENA 02 - EXT. QUINTAL - NOITE" in payload["content"]


def test_script_payload_normalizes_inline_scene_heading_from_model_response() -> None:
    payload = normalize_script_payload(
        {
            "title": "O Relampago de Papel",
            "content": """
FADE IN:

CENA 1 - INT. QUARTO DE IAN - NOITE

Chuva forte. IAN desenha um cavalo no caderno.

IAN
(sussurrando)
Não acredito...

CENA 2 - EXT. ESCOLA - DIA

Ian tenta brincar com colegas, mas o passaro de fogo assusta as criancas.

FADE OUT.
""",
        },
        default_title="O Relampago de Papel",
        language="pt-BR",
        target_duration_seconds=300,
    )

    assert "CENA 01 - INT. QUARTO DE IAN - NOITE" in payload["content"]
    assert "CENA 02 - EXT. ESCOLA - DIA" in payload["content"]
    assert "INT. CENA 1 - DIA" not in payload["content"]
    assert "FADE IN: CENA 1" not in payload["content"]


def test_script_payload_removes_screenplay_parentheticals() -> None:
    payload = normalize_script_payload(
        {
            "title": "A Porta Azul",
            "content": """
FADE IN:

CENA 01
INT. LOJA FECHADA - NOITE

Marco fecha o caixa (a pressao pesa no ambiente).

MARCO (CONT.)
(baixo)
Eu preciso terminar isso agora.

LIA (V.O.)
Ninguem vai esperar.

FADE OUT.
""",
        },
        default_title="A Porta Azul",
        language="pt-BR",
        target_duration_seconds=300,
    )

    content = payload["content"]
    assert "Marco fecha o caixa." in content
    assert "\nMARCO\nEu preciso terminar isso agora." in content
    assert "\nLIA\nNinguem vai esperar." in content
    assert "(CONT.)" not in content
    assert "(V.O.)" not in content
    assert "(baixo)" not in content
    assert "(" not in content
    assert ")" not in content


def test_screenplay_válidator_rejects_technical_planning_document() -> None:
    errors = screenplay_validation_errors(
        """
ROTEIRO DE PRODUCAO

CENA 1 - GANCHO
Objetivo: apresentar conflito.
Acao: Clara abre a carta.
Indicacao para video: push-in lento.
"""
    )

    assert "faltou FADE IN" in errors
    assert "faltou slugline INT./EXT." in errors
    assert "conteúdo contem rotulos tecnicos" in errors


def test_screenplay_validator_accepts_combined_scene_heading() -> None:
    """Formato canonico: "CENA NN - INT./EXT. LOCAL - PERIODO" em UMA linha."""
    errors = screenplay_validation_errors(
        """
FADE IN:

CENA 01 - INT. SALA - DIA

Clara encontra a carta.

CENA 02 - EXT. QUINTAL - NOITE

Clara encara a janela acesa.

FADE OUT.
"""
    )

    assert errors == []


def test_screenplay_validator_rejects_heading_without_slugline() -> None:
    errors = screenplay_validation_errors(
        """
FADE IN:

CENA 01 - INT. SALA - DIA

Clara encontra a carta.

CENA 2 - GANCHO

Clara encara a janela acesa.

FADE OUT.
"""
    )

    assert "cabecalho de cena deve seguir o padrao CENA NN - INT./EXT. LOCAL - PERIODO" in errors


def test_screenplay_validator_rejects_forbidden_transitions() -> None:
    errors = screenplay_validation_errors(
        """
FADE IN:

CENA 01 - INT. SALA - DIA

Clara encontra a carta.

CORTE PARA:

CENA 02 - EXT. QUINTAL - NOITE

Clara encara a janela acesa.

FADE OUT.
"""
    )

    assert any("CORTE PARA" in error for error in errors)


def test_screenplay_válidator_rejects_compacted_inline_numbered_sluglines() -> None:
    errors = screenplay_validation_errors(
        """
CENA 01
INT. CENA 1 - DIA

FADE IN: 1. INT. MERCADO NOTURNO - NOITE Um labirinto de barracas.
OMERO vende memórias. 2. INT. BARRACA DE OMERO - MAIS TARDE Omero abre um caderno.

FADE OUT.
"""
    )

    assert "FADE IN precisa ficar em linha propria" in errors
    assert "sluglines numeradas não podem ficar dentro de parágrafos" in errors
    assert "slugline generica INT. CENA precisa ser substituida por local real" in errors


def test_screenplay_validator_rejects_location_used_as_dialogue_cue() -> None:
    errors = screenplay_validation_errors(
        """
TITULO: A carta azul

FADE IN:

CENA 01
INT. SALA DA CASA - NOITE

CLARA segura a carta dobrada.

SALA DA CASA
Eu não consigo abrir isso sozinha.

FADE OUT.
"""
    )

    assert "cue de dialogo usa nome de local: SALA DA CASA" in errors


def test_script_payload_repairs_compacted_inline_numbered_sluglines() -> None:
    payload = normalize_script_payload(
        {
            "title": "Memorias de Omero",
            "content": """
FADE IN: 1. INT. MERCADO NOTURNO - NOITE Um labirinto de barracas.
OMERO vende memórias. 2. INT. BARRACA DE OMERO - MAIS TARDE Omero abre um caderno.

FADE OUT.
""",
        },
        default_title="Memorias de Omero",
        language="pt-BR",
        target_duration_seconds=300,
    )

    content = payload["content"]
    assert "FADE IN: 1." not in content
    assert "1. INT." not in content
    assert "2. INT." not in content
    assert "FADE IN:\n\nCENA 01 - INT. MERCADO NOTURNO - NOITE" in content
    assert "CENA 02 - INT. BARRACA DE OMERO - MAIS TARDE" in content


def test_story_idea_db_text_truncates_long_protagonist_for_varchar_column() -> None:
    payload = {
        "protagonist": (
            "Tadeu, 38 anos, mergulhador de resgate, ex-fuzileiro naval, solteiro, "
            "com pésadelos recorrentes de um naufragio que não conseguiu evitar. "
            "Seu desejo e provar que e capaz de salvar vidas sob pressão extrema, "
            "mesmo quando a plataforma inteira está prestes a explodir e todos duvidam dele."
        )
    }

    protagonist = _story_idea_db_text(payload, "protagonist", "story_idea")

    assert len(protagonist) <= 220
    assert protagonist.endswith("...")


def test_script_payload_preserves_embedded_production_plan_separately() -> None:
    payload = normalize_script_payload(
        {
            "title": "A carta azul",
            "content": """
TITULO: A carta azul

FADE IN:

CENA 01
INT. SALA - DIA

Clara encontra uma carta azul sobre a mesa e percebe que a mensagem chegou tarde.

FADE OUT.
""",
            "production_plan": {
                "scenes": [
                    {
                        "scene_number": 1,
                        "title": "A chegada",
                        "summary": "Clara encontra a carta.",
                        "duration_seconds": 60,
                        "shots": [
                            {
                                "shot_number": 1,
                                "duration_seconds": 60,
                                "narration_text": "Clara encontra a carta.",
                                "dialogue_text": "",
                                "action": "Clara pega a carta sobre a mesa.",
                                "emotion": "descoberta",
                                "visual_composition": "Plano vertical com carta e rosto.",
                                "camera_movement": "push-in lento",
                                "generation_type": "IMAGE_TO_VIDEO",
                            }
                        ],
                    }
                ]
            },
        },
        default_title="A carta azul",
        language="pt-BR",
        target_duration_seconds=60,
    )

    assert payload["production_plan"]["scenes"][0]["shots"][0]["duration_seconds"] == 8
    assert "production_plan" not in payload["content"]


def test_scene_plan_payload_normalizes_shots_to_package_duration_values() -> None:
    payload = normalize_scene_plan_payload(
        {
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "Cena longa",
                    "summary": "Clara entende a carta.",
                    "duration_seconds": 60,
                    "shots": [
                        {
                            "shot_number": 1,
                            "duration_seconds": 60,
                            "narration_text": "Clara abre a carta.",
                            "dialogue_text": "",
                            "action": "Clara abre a carta diante da janela.",
                            "emotion": "descoberta",
                            "visual_composition": "Plano vertical com carta e rosto.",
                            "camera_movement": "push-in lento",
                            "generation_type": "IMAGE_TO_VIDEO",
                        }
                    ],
                }
            ]
        },
        60,
    )

    shots = [shot for scene in payload["scenes"] for shot in scene["shots"]]
    assert sum(shot["duration_seconds"] for shot in shots) == 64
    assert all(shot["duration_seconds"] in VIDEO_CLIP_ALLOWED_SECONDS for shot in shots)
    assert payload["scenes"][0]["duration_seconds"] == 64


def test_scene_plan_payload_uses_script_scene_markers_when_ai_returns_one_scene() -> None:
    script = """CENA 1
INT. SALA DE ESTAR - FINAL DE TARDE
DURACAO: 60s
OBJETIVO: Apresentar a chegada inesperada.

CENA 2
EXT. QUINTAL - NOITE
DURACAO: 60s
OBJETIVO: Revelar o segredo.
"""
    payload = normalize_scene_plan_payload_from_script(
        {
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "Cena única",
                    "summary": "Resumo geral.",
                    "duration_seconds": 120,
                    "shots": [
                        {
                            "shot_number": 1,
                            "duration_seconds": 120,
                            "narration_text": "Resumo geral.",
                            "dialogue_text": "",
                            "action": "Resumo geral.",
                            "emotion": "tensão",
                            "visual_composition": "Plano vertical.",
                            "camera_movement": "push-in",
                            "generation_type": "IMAGE_TO_VIDEO",
                        }
                    ],
                }
            ]
        },
        120,
        script,
    )

    assert [scene["title"] for scene in payload["scenes"]] == [
        "INT. SALA DE ESTAR - FINAL DE TARDE",
        "EXT. QUINTAL - NOITE",
    ]


def test_scene_plan_payload_can_be_derived_from_structured_script_without_llm() -> None:
    script = """TITULO: O Relampago de Papel

FADE IN:

CENA 01
INT. QUARTO DE IAN - NOITE

Ian desenha um cavalo no caderno enquanto a chuva bate na janela.

CENA 02
EXT. ESCOLA - DIA

Ian tenta brincar com colegas, mas o passaro de fogo assusta as criancas.

FADE OUT.
"""

    payload = scene_plan_payload_from_script_content(script, 120)

    assert payload is not None
    assert [scene["title"] for scene in payload["scenes"]] == [
        "INT. QUARTO DE IAN - NOITE",
        "EXT. ESCOLA - DIA",
    ]
    assert sum(scene["duration_seconds"] for scene in payload["scenes"]) == 120
    assert all(
        shot["duration_seconds"] in VIDEO_CLIP_ALLOWED_SECONDS
        for scene in payload["scenes"]
        for shot in scene["shots"]
    )
    assert all(
        not shot["action"].rstrip().endswith((" de", " para", " com", " e"))
        for scene in payload["scenes"]
        for shot in scene["shots"]
    )


def test_scene_plan_splits_each_scene_into_ordered_visual_beats() -> None:
    script = """CENA 01
INT. OFICINA - NOITE

Lia abre a porta. Ela acende a luz. Um ruído vem do armário. Lia se aproxima.

LIA
Tem alguém aí?

Ela segura a maçaneta. A porta range. Uma carta cai no chão. Lia lê o nome.
"""

    payload = scene_plan_payload_from_script_content(script, 48)

    assert payload is not None
    shots = payload["scenes"][0]["shots"]
    assert len(shots) > 1
    assert len({shot["action"] for shot in shots}) == len(shots)
    assert "Lia abre a porta" in shots[0]["action"]
    assert "Lia lê o nome" in shots[-1]["action"]
    assert all("Tem alguém aí" not in shot["action"] for shot in shots)


def test_scene_plan_rejects_duplicate_actions_from_generated_plan() -> None:
    repeated_shot = {
        "duration_seconds": 6,
        "narration_text": "Lia observa a porta.",
        "dialogue_text": "",
        "action": "Lia observa a porta.",
        "emotion": "tensão",
        "visual_composition": "Plano médio.",
        "camera_movement": "fixa",
        "generation_type": "TEXT_TO_VIDEO",
    }
    payload = {
        "scenes": [
            {
                "scene_number": 1,
                "title": "Oficina",
                "summary": "Lia observa a porta.",
                "duration_seconds": 12,
                "shots": [
                    {**repeated_shot, "shot_number": 1},
                    {**repeated_shot, "shot_number": 2},
                ],
            }
        ]
    }

    with pytest.raises(GenerationOutputError, match="distinct action"):
        normalize_scene_plan_payload(payload, 12)


def test_scene_plan_payload_adds_spatial_continuity_defaults() -> None:
    payload = normalize_scene_plan_payload(
        {
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "Consulta",
                    "summary": "Lia conversa com Marco.",
                    "duration_seconds": 8,
                    "shots": [
                        {
                            "shot_number": 1,
                            "duration_seconds": 8,
                            "narration_text": "Lia mostra um tablet.",
                            "dialogue_text": "",
                            "action": "Lia mostra um tablet para Marco.",
                            "emotion": "tensao",
                            "visual_composition": "Plano medio vertical.",
                            "camera_movement": "camera fixa",
                            "generation_type": "IMAGE_TO_VIDEO",
                        }
                    ],
                }
            ]
        },
        8,
    )

    scene = payload["scenes"][0]
    shot = scene["shots"][0]
    assert "spatial_layout" in scene
    assert "spatial_continuity" in shot
    assert "lados da tela" in scene["spatial_layout"]
    assert "esquerda/direita" in shot["spatial_continuity"]


def test_script_payload_builds_content_from_scene_list_when_content_is_empty() -> None:
    payload = normalize_script_payload(
        {
            "content": "",
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "A chegada",
                    "action": "Clara encontra a carta na porta.",
                    "video_direction": "Dolly in lento ate a mao dela.",
                }
            ],
        },
        default_title="A carta azul",
        language="pt-BR",
        target_duration_seconds=300,
    )

    assert "FADE IN:" in payload["content"]
    assert "CENA 01" in payload["content"]
    assert "INT. A CHEGADA - DIA" in payload["content"]
    assert "Clara encontra a carta na porta." in payload["content"]
    assert "Titulo:" not in payload["content"]
    assert "Acao:" not in payload["content"]
    assert "Dolly in lento" not in payload["content"]


def test_fallback_script_content_from_bible_is_usable_when_model_returns_empty_script() -> None:
    content = _fallback_script_content_from_bible(
        {
            "logline": "Uma filha recebe uma mensagem atrasada do pai.",
            "characters": [{"name": "Clara", "role": "filha"}],
            "locations": [{"name": "Casa da familia"}],
        },
        "A mensagem atrasada",
        300,
    )

    assert "TITULO: A mensagem atrasada" in content
    assert "FADE IN:" in content
    assert "CENA 01" in content
    assert "INT. CASA DA FAMILIA - FIM DE TARDE" in content
    assert "Indicacao para video" not in content
    assert "Objetivo dramatico" not in content


def test_fallback_script_content_from_idea_scales_scene_count_with_duration() -> None:
    content = _fallback_script_content_from_idea(
        {
            "title": "A promessa longa",
            "premise": "Uma familia precisa sustentar uma verdade dificil.",
            "protagonist": "Clara",
        },
        "A promessa longa",
        900,
    )

    assert expected_script_scene_count(300) == 5
    assert expected_script_scene_count(900) == 12
    assert content.count("CENA ") == 12
    assert "CENA 12" in content


def test_idea_script_contract_uses_canonical_protagonist_name_and_dialogue_rules() -> None:
    idea = SimpleNamespace(
        title="O farol apagado",
        premise="Uma faroleira mantém a luz acesa.",
        hook="A cidade quer apagar o farol.",
        protagonist="Lia, uma faroleira teimosa",
        payload={
            "conflict": "A cidade quer desligar o farol.",
            "stakes": "Um barco pode desaparecer.",
            "resolution": "Lia prova que a luz ainda salva.",
        },
    )
    briefing = SimpleNamespace(
        theme="esperança",
        genre="drama",
        primary_emotion="esperança",
        audience="público geral",
        constraints=[],
        visual_style="cinemático realista",
    )

    contract = _idea_script_contract(cast(Any, idea), cast(Any, briefing))

    assert contract["characters"][0]["name"] == "Lia"
    assert contract["characters"][0]["description"] == "Lia, uma faroleira teimosa"
    assert "usar LIA como cue de dialogo da protagonista" in contract["dialogue_rules"]
