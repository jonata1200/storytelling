from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.providers.llm.types import LLMResult
from app.visual_bible.profiles import (
    _semantic_deduplicate_locations,
    _story_idea_protagonist_name,
)
from app.visual_bible.script_profiles import (
    SCRIPT_EXTRACTION_CHUNK_CHARS,
    _apply_visual_design,
    _extraction_prompt,
    _llm_extract_characters_and_locations,
    _looks_like_non_character_name,
    _merge_extracted_items,
    _script_character_items,
    _script_character_names,
    _script_extraction_chunks,
    _script_location_items,
    visual_extraction_coverage,
)
from app.visual_bible.service import _apply_script_gender_evidence, _visual_story_context


def test_explicit_script_gender_overrides_missing_or_incorrect_extraction() -> None:
    items = [{"name": "Elias", "gender": "feminino", "evidence_text": []}]
    script = "ELIAS, um homem de olhar vazio mas mãos precisas, toca o mapa."

    result = _apply_script_gender_evidence(items, script)

    assert result[0]["gender"] == "masculino"
    assert result[0]["evidence_text"] == ["ELIAS, um homem"]


def test_script_extraction_chunks_preserve_the_entire_script() -> None:
    script = "CENA 1\n" + ("A" * (SCRIPT_EXTRACTION_CHUNK_CHARS + 25)) + "\nFIM\n"

    chunks = _script_extraction_chunks(script)

    assert len(chunks) > 1
    assert "".join(chunks) == script
    assert all(len(chunk) <= SCRIPT_EXTRACTION_CHUNK_CHARS for chunk in chunks)


def test_script_extraction_chunks_keep_complete_scenes_when_they_fit() -> None:
    first_scene = "CENA 1\nINT. CASA - DIA\n" + ("Ação da primeira cena. " * 170) + "\n"
    second_scene = "CENA 2\nEXT. RUA - NOITE\n" + ("Ação da segunda cena. " * 170) + "\n"

    chunks = _script_extraction_chunks(first_scene + second_scene)

    assert chunks == [first_scene, second_scene]


def test_merge_extracted_items_combines_evidence_and_keeps_explicit_attributes() -> None:
    merged = _merge_extracted_items(
        [
            {
                "name": "Clara",
                "role": "protagonista",
                "hair": "cabelo preto",
                "scene_numbers": [1],
                "evidence_text": ["Clara prende o cabelo preto."],
            },
            {
                "name": "CLARA",
                "base_outfit": "casaco azul",
                "scene_numbers": [3, 1],
                "evidence_text": ["Clara veste o casaco azul."],
            },
        ]
    )

    assert merged == [
        {
            "name": "Clara",
            "role": "protagonista",
            "hair": "cabelo preto",
            "base_outfit": "casaco azul",
            "scene_numbers": [1, 3],
            "evidence_text": [
                "Clara prende o cabelo preto.",
                "Clara veste o casaco azul.",
            ],
        }
    ]


def test_script_location_items_extract_sluglines_with_scene_evidence() -> None:
    locations = _script_location_items(
        "CENA 1\nEXT. ZONA INDUSTRIAL - NOITE\nAção.\n"
        "CENA 2\nINT. TORRE DE TRANSMISSÃO - DIA\nAção.\n"
    )

    assert [item["name"] for item in locations] == [
        "Zona Industrial",
        "Torre De Transmissão",
    ]
    assert locations[0]["scene_numbers"] == [1]
    assert locations[0]["evidence_text"] == ["EXT. ZONA INDUSTRIAL - NOITE"]


def test_script_parser_keeps_individually_identifiable_role_characters() -> None:
    items = _script_character_items(
        "CENA 1\nINT. CASA - NOITE\nMÃE\nVolte aqui.\n"
        "MENINA (10) fecha a porta.\nGUARDA\nPare.\n"
    )

    assert [item["name"] for item in items] == ["Mãe", "Menina", "Guarda"]
    assert [item["role"] for item in items] == ["mae", "menina", "guarda"]


def test_script_location_parser_accepts_combined_headings_and_keeps_subareas() -> None:
    locations = _script_location_items(
        "CENA 1\nINT./EXT. HOSPITAL - NOITE\nAção.\n"
        "CENA 2\nI/E HOSPITAL - CORREDOR - MADRUGADA\nAção.\n"
    )

    assert [item["name"] for item in locations] == ["Hospital", "Hospital - Corredor"]


def test_script_location_parser_strips_midday_and_dusk_periods() -> None:
    # "A Última Semente": MEIO-DIA/ANOITECER colados ao nome do local
    # impediam o casamento com o LLM ("Roça De Maria - Meio-Dia").
    locations = _script_location_items(
        "CENA 1\nEXT. ROÇA DE MARIA - MEIO-DIA\nAção.\n"
        "CENA 3\nEXT. ROÇA DE MARIA - ENTARDECER\nAção.\n"
        "CENA 4\nEXT. POÇO DE MARIA - ANOITECER\nAção.\n"
    )

    assert [item["name"] for item in locations] == ["Roça De Maria", "Poço De Maria"]


def test_location_deduplication_does_not_merge_distinct_subareas() -> None:
    locations = _semantic_deduplicate_locations(
        [
            {"name": "Hospital - Corredor", "description": "corredor principal"},
            {"name": "Hospital - Quarto 203", "description": "quarto de internação"},
        ]
    )

    assert [item["name"] for item in locations] == [
        "Hospital - Corredor",
        "Hospital - Quarto 203",
    ]


def test_location_deduplication_merges_descriptive_qualifier_of_same_space() -> None:
    locations = _semantic_deduplicate_locations(
        [
            {"name": "Galpão", "description": "espaço de escala média"},
            {"name": "Galpão Abandonado", "description": "galpão escuro e marcado pelo tempo"},
        ]
    )

    assert [item["name"] for item in locations] == ["Galpão Abandonado"]


def test_fade_to_black_is_not_a_character() -> None:
    assert _looks_like_non_character_name("Fade To Black")
    assert _looks_like_non_character_name("FADE TO BLACK")
    assert _script_character_items("CENA 1\nINT. CASA - NOITE\nFADE TO BLACK.\n") == []


def test_post_slugline_atmosphere_line_is_not_a_character() -> None:
    # "O Farol do Silêncio": a linha órfã após o slugline descreve o clima,
    # não um personagem — não pode virar candidato ("De Tempestade").
    names = _script_character_names("EXT. FAROL - NOITE\n\n DE TEMPESTADE\n\nAção.\n")

    assert names == []


def test_action_line_introduces_named_character() -> None:
    # Elias nunca tem fala em cue e só aparece em linhas de ação: a
    # introdução "ELIAS, faroleiro..." deve criar o candidato.
    script = (
        "CENA 1\nINT. CASA - NOITE\nAção.\n"
        "ELIAS, faroleiro de barba grisalha e olhos cansados, sobe correndo.\n"
    )

    assert _script_character_names(script) == ["Elias"]


def test_action_line_character_needs_lowercase_occurrence() -> None:
    # "O Piano na Praça": "Um HOLOFOTE IMPROVISADO, pendurado..." e "as teclas
    # se mover SOZINHAS, tocando..." criavam os falsos personagens
    # "Improvisado" e "Sozinhas" — palavras em caps de DESTAQUE que só existem
    # naquela linha e recebem aposto verbal (particípio/gerúndio).
    highlighted_caps = (
        "CENA 1\nEXT. PRAÇA - ENTARDECER\n"
        "Um HOLOFOTE IMPROVISADO, pendurado em um poste, ilumina o piano.\n"
        "As teclas começam a se mover SOZINHAS, tocando uma melodia.\n"
    )
    assert _script_character_names(highlighted_caps) == []

    # Personagem de verdade: aposto substantivo + ocorrência em minúsculo na
    # ação ("Elias respira fundo") — o candidato é mantido.
    with_lowercase = highlighted_caps + (
        "ELIAS, faroleiro de barba grisalha, entra no quadro.\n"
        "Elias respira fundo e toca.\n"
    )
    assert _script_character_names(with_lowercase) == ["Elias"]


def test_emphasized_object_and_group_caps_are_not_characters() -> None:
    script = (
        "CENA 1\nINT. VAGÃO - NOITE\n"
        "Um RELÓGIO DIGITAL marca a hora. PASSAGEIROS gritam, e a LUZ DO FAROL pisca.\n"
        "CLARA, engenheira de sistemas, corre pelo vagão.\n"
    )

    assert _script_character_names(script) == ["Clara"]


def test_common_noun_caps_are_not_characters() -> None:
    # "O Silêncio do Elevador": "Um CORPO está caído no fundo" criava o falso
    # personagem "Corpo" — substantivo comum em caps de DESTAQUE, não pessoa.
    script = (
        "CENA 1\nINT. ELEVADOR - NOITE\n"
        "Um CORPO está caído no fundo do poço.\n"
        "VALENTINA COSTA\nGustavo, você estava perto da porta?\n"
    )

    assert _script_character_names(script) == ["Valentina Costa"]


def test_isolated_surname_is_not_a_separate_character() -> None:
    # "VALENTINA COSTA, MARCOS" — o regex do segundo passe captura só o último
    # token seguido de vírgula ("COSTA,"), criando o falso personagem "Costa"
    # além de "Valentina Costa". O sobrenome isolado é a mesma pessoa.
    script = (
        "CENA 1\nINT. ELEVADOR - NOITE\n"
        "Cinco pessoas estão presas: VALENTINA COSTA, MARCOS, DANIELA e GUSTAVO.\n"
        "VALENTINA COSTA\nGustavo, você estava perto da porta?\n"
        "MARCOS\nO que é isso no seu uniforme?\n"
        "DANIELA\nEu nunca contei isso pra ninguém.\n"
        "GUSTAVO\nDeve ter sido no café da manhã.\n"
    )

    assert _script_character_names(script) == ["Valentina Costa", "Marcos", "Daniela", "Gustavo"]


def test_participle_caps_are_not_characters() -> None:
    # "O Silêncio do Elevador": "o botão de emergência foi ARRANCADO, deixando
    # um buraco vazio" criava o falso personagem "Arrancado" — o nome em si é
    # um particípio (-ado), nunca uma pessoa. A guarda de aposto verbal não
    # pega esse caso porque "arrancado" reaparece em minúsculo como VERBO.
    script = (
        "CENA 1\nINT. ELEVADOR - NOITE\n"
        "O botão de emergência foi ARRANCADO, deixando um buraco vazio e fios expostos.\n"
        "VALENTINA COSTA\nMarcos, o que você está fazendo?\n"
    )

    assert _script_character_names(script) == ["Valentina Costa"]


def test_reflection_of_character_is_not_a_separate_character() -> None:
    # "A Última Mensagem": "REFLEXO DE LÚCIA" é o reflexo da pessoa no espelho,
    # não um personagem distinto. A Lúcia real é quem fala/age — o cue do
    # reflexo não pode virar um segundo personagem nem engolir a Lúcia.
    script = (
        "CENA 1\nINT. QUARTO - NOITE\n"
        "LÚCIA estende a mão trêmula.\n"
        "REFLEXO DE LÚCIA\nVocê sabe o que precisa fazer.\n"
        "LÚCIA\nIsso não é possível.\n"
    )

    assert _script_character_names(script) == ["Lúcia"]


def test_story_idea_protagonist_name_accepts_serialized_dict() -> None:
    # O Idea Lab grava o protagonista como dict serializado em string.
    assert (
        _story_idea_protagonist_name("{'name': 'Elias', 'age': 55, 'profession': 'Faroleiro'}")
        == "Elias"
    )
    assert _story_idea_protagonist_name("Maria, agricultora de 60 anos") == "Maria"
    assert _story_idea_protagonist_name("") == ""


def test_character_aliases_are_resolved_globally() -> None:
    merged = _merge_extracted_items(
        [
            {"name": "Helena", "role": "médica"},
            {"name": "Doutora", "aliases": ["Dra. Helena"], "hair": "cabelo preto"},
        ],
        entity_kind="character",
    )

    assert len(merged) == 1
    assert merged[0]["name"] == "Helena"
    assert merged[0]["hair"] == "cabelo preto"


def test_visual_direction_fills_only_missing_fields_and_preserves_evidence() -> None:
    original = {
        "name": "Mãe",
        "role": "mae",
        "hair": "cabelo grisalho",
        "base_outfit": "",
        "evidence_text": ["MÃE ajeita o cabelo grisalho."],
    }
    result = _apply_visual_design(
        [original],
        [
            {
                "name": "Mãe",
                "hair": "cabelo preto",
                "base_outfit": "uniforme de fábrica gasto",
            }
        ],
        entity_kind="character",
    )

    assert result[0]["hair"] == "cabelo grisalho"
    assert result[0]["base_outfit"] == "uniforme de fábrica gasto"
    assert result[0]["evidence_text"] == original["evidence_text"]


def test_visual_extraction_coverage_reports_missing_parser_candidates() -> None:
    script = "CENA 1\nINT. CASA - NOITE\nMÃE\nEntre.\n"

    assert visual_extraction_coverage(script, [], []) == {
        "missing_characters": ["Mãe"],
        "missing_locations": ["Casa"],
    }


def test_location_extraction_prompt_is_grounded_in_story_context() -> None:
    prompt = _extraction_prompt(
        "CENA 1\nINT. OFICINA - NOITE",
        1,
        1,
        '{"premise":"Uma mecânica sobrevive numa cidade inundada"}',
    )

    assert "Uma mecânica sobrevive numa cidade inundada" in prompt
    assert "combinações decorativas genéricas" in prompt
    assert "Cruze slugline, ações da cena e contexto canônico" in prompt


def test_visual_story_context_includes_briefing_art_direction() -> None:
    idea = SimpleNamespace(
        title="A Ponte",
        hook="Uma travessia impossível",
        premise="Mãe e filha atravessam uma cidade inundada",
        payload={},
    )
    briefing = SimpleNamespace(
        genre="Drama",
        country_context="Brasil",
        visual_style="realismo brasileiro dos anos 1990",
        primary_emotion="esperança",
    )

    context = _visual_story_context(idea, briefing)  # type: ignore[arg-type]

    assert "realismo brasileiro dos anos 1990" in context
    assert '"country_context": "Brasil"' in context


@pytest.mark.asyncio
async def test_llm_extraction_analyzes_all_chunks_and_uses_structured_schema(
    monkeypatch: Any,
) -> None:
    calls = []

    class Provider:
        async def generate_structured(self, request: Any) -> LLMResult:
            calls.append(request)
            number = len(calls)
            return LLMResult(
                content={
                    "characters": [
                        {
                            "name": "Clara",
                            "role": "protagonista",
                            "hair": "preto" if number == 1 else "",
                            "base_outfit": "casaco azul" if number == 2 else "",
                            "scene_numbers": [number],
                            "evidence_text": [f"evidência {number}"],
                        }
                    ],
                    "locations": [],
                },
                model="model",
                provider="provider",
            )

    async def configured_provider(*_args: Any) -> tuple[Provider, str]:
        return Provider(), "model"

    monkeypatch.setattr(
        "app.generation.model_settings.llm_provider_for_task",
        configured_provider,
    )
    script = "CENA 1\n" + ("A" * SCRIPT_EXTRACTION_CHUNK_CHARS) + "\nCENA 2\n"

    characters, locations = await _llm_extract_characters_and_locations(
        SimpleNamespace(), uuid4(), script
    )

    extraction_calls = [call for call in calls if call.task == "extract_characters_locations"]
    assert len(extraction_calls) == len(_script_extraction_chunks(script))
    assert calls[-1].task == "design_visual_bible_profiles"
    assert all(call.output_schema for call in calls)
    assert characters[0]["scene_numbers"] == list(range(1, len(extraction_calls) + 1))
    assert characters[0]["hair"] == "preto"
    assert characters[0]["base_outfit"] == "casaco azul"
    assert locations == []


@pytest.mark.asyncio
async def test_visual_direction_failure_keeps_grounded_extraction(monkeypatch: Any) -> None:
    class Provider:
        async def generate_structured(self, request: Any) -> LLMResult:
            if request.task == "design_visual_bible_profiles":
                raise RuntimeError("direção visual indisponível")
            return LLMResult(
                content={
                    "characters": [
                        {
                            "name": "Mãe",
                            "role": "mae",
                            "hair": "cabelo grisalho",
                            "scene_numbers": [1],
                            "evidence_text": ["MÃE ajeita o cabelo grisalho."],
                        }
                    ],
                    "locations": [],
                },
                model="model",
                provider="provider",
            )

    async def configured_provider(*_args: Any) -> tuple[Provider, str]:
        return Provider(), "model"

    monkeypatch.setattr(
        "app.generation.model_settings.llm_provider_for_task",
        configured_provider,
    )

    characters, _locations = await _llm_extract_characters_and_locations(
        SimpleNamespace(),
        uuid4(),
        "CENA 1\nINT. CASA - NOITE\nMÃE ajeita o cabelo grisalho.\n",
    )

    assert characters[0]["name"] == "Mãe"
    assert characters[0]["hair"] == "cabelo grisalho"
