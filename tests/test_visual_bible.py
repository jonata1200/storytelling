from typing import Any
from uuid import uuid4

import pytest

from app.projects.models import Artifact
from app.visual_bible import service as visual_bible_service
from app.visual_bible.models import Character, CharacterVersion
from app.visual_bible.service import (
    _character_profile,
    _location_profile,
    _merge_profile_items,
    _payload_section,
    _profile_items,
    _prop_profile,
    _repair_missing_character_names,
    _script_character_names,
    _script_location_profiles,
    _script_prop_profiles,
    default_views_for,
    initial_view_for,
    regenerate_visual_reference,
    update_visual_target_prompt,
    validated_visual_reference_views,
    visual_profile_validation_errors,
    visual_reference_aspect_ratio,
    visual_reference_prompt,
)


def test_default_character_views_include_required_reference_sheet_items() -> None:
    views = default_views_for("character")

    assert "front_portrait" in views
    assert "left_profile" in views
    assert "right_profile" in views
    assert "back_view" in views
    assert "full_body" in views
    assert "expression_sheet" in views
    assert "pose_sheet" in views
    assert "scale_reference" in views


def test_initial_visual_reference_is_single_canonical_view() -> None:
    assert initial_view_for("character") == "front_portrait"
    assert initial_view_for("location") == "establishing"
    assert initial_view_for("prop") == "front"

    for target_kind in ["character", "location", "prop"]:
        assert initial_view_for(target_kind) in default_views_for(target_kind)


def test_visual_reference_views_reject_invalid_values() -> None:
    assert validated_visual_reference_views("prop", ["front", "side"]) == ["front", "side"]

    with pytest.raises(ValueError, match="View type invalido"):
        validated_visual_reference_views("prop", ["front", "bad/view"])


def test_visual_reference_prompt_uses_canonical_profile_prompt() -> None:
    profile = {
        "name": "Helena",
        "canonical_prompt": "Helena, 35, expressive detective, rainy noir lighting",
    }

    prompt = visual_reference_prompt(profile, "front_portrait")

    assert prompt.startswith(
        "Helena, 35, expressive detective, rainy noir lighting. Vista de referencia: "
        "front_portrait."
    )
    assert "fundo cinza neutro de estudio" in prompt
    assert "Proporcao obrigatoria: 9:16" in prompt
    assert "referencia de continuidade para storyboard e video" in prompt
    assert "identidade visual consistente" in prompt


def test_visual_reference_prompts_are_distinct_by_view_type() -> None:
    profile = {"name": "Carta azul", "canonical_prompt": "Carta azul antiga, papel gasto"}

    front = visual_reference_prompt(profile, "front")
    side = visual_reference_prompt(profile, "side")

    assert front != side
    assert "vista frontal" in front
    assert "vista lateral" in side


def test_visual_profiles_accept_text_items_from_story_bible() -> None:
    character = _character_profile("Clara")
    location = _location_profile("Casa da familia")
    prop = _prop_profile("Carta azul")

    assert character["name"] == "Clara"
    assert character["role"] == "personagem"
    assert location["name"] == "Casa da familia"
    assert prop["name"] == "Carta azul"


def test_visual_profiles_generate_professional_canonical_prompts() -> None:
    character = _character_profile(
        {
            "name": "Clara",
            "role": "filha",
            "hair": "cabelo castanho curto",
            "base_outfit": "casaco verde gasto",
        }
    )
    location = _location_profile({"name": "Casa da familia", "lighting": "luz fria da janela"})
    prop = _prop_profile({"name": "Carta azul", "material": "papel amassado"})

    assert (
        "Fotorrealista, hiper realista, foto de uma pessoa" in character["canonical_prompt"]
    )
    assert "fotografia de referencia de elenco" in character["canonical_prompt"]
    assert "Manter exatamente o mesmo rosto" in character["canonical_prompt"]
    assert character["narrative_profile"]["name"] == "Clara"
    assert character["gender"] == "personagem feminino"
    assert "Genero visual obrigatorio: feminino" in character["canonical_prompt"]
    assert character["visual_profile"]["hair"] == "cabelo castanho curto"
    assert "cabelo castanho curto" in character["canonical_prompt"]
    assert "Figurino base exclusivo" in character["canonical_prompt"]
    assert (
        "Fotorrealista, hiper realista, fotografia de arquitetura"
        in location["canonical_prompt"]
    )
    assert "ambiente vazio e claramente filmavel" in location["canonical_prompt"]
    assert "Nenhuma pessoa presente" in location["canonical_prompt"]
    assert "Fotorrealista, hiper realista, fotografia de produto" in prop["canonical_prompt"]
    assert "continuidade cinematografica" in prop["canonical_prompt"]
    assert "papel amassado" in prop["canonical_prompt"]
    assert location["narrative_profile"]["name"] == "Casa da familia"
    assert prop["visual_profile"]["material"] == "papel amassado"


def test_visual_profile_validation_rejects_generic_profiles() -> None:
    location = _location_profile({"name": "Local principal"})
    prop = _prop_profile({"name": "Objeto de revelacao"})

    assert "name generico: Local principal" in visual_profile_validation_errors(
        "location", location
    )
    assert "name generico: Objeto de revelacao" in visual_profile_validation_errors(
        "prop", prop
    )


def test_visual_profile_validation_accepts_specific_profiles() -> None:
    character = _character_profile(
        {
            "name": "Clara",
            "role": "filha",
            "hair": "cabelo castanho curto",
            "base_outfit": "casaco verde gasto",
            "palette": ["verde", "creme"],
        }
    )
    location = _location_profile(
        {
            "name": "Cozinha de Dona Lourdes",
            "description": "cozinha antiga onde a promessa reaparece",
            "layout": "fogao ao fundo e mesa no centro",
            "lighting": "luz fria pela janela lateral",
        }
    )
    prop = _prop_profile(
        {
            "name": "Carta azul",
            "material": "papel envelhecido",
            "color": "azul desbotado",
            "narrative_importance": "revela a promessa quebrada",
        }
    )

    assert visual_profile_validation_errors("character", character) == []
    assert visual_profile_validation_errors("location", location) == []
    assert visual_profile_validation_errors("prop", prop) == []


def test_merge_profile_items_replaces_generic_story_bible_items_with_script_fallbacks() -> None:
    merged = _merge_profile_items(
        "location",
        [{"name": "Local principal"}],
        [{"name": "Cozinha De Dona Lourdes"}, {"name": "Quintal"}],
    )

    assert [item["name"] for item in merged] == ["Cozinha De Dona Lourdes", "Quintal"]


def test_character_profile_formats_structured_outfit_as_prompt_text() -> None:
    character = _character_profile(
        {
            "name": "Dona Lourdes",
            "base_outfit": {
                "peca_principal": "vestido azul indigio",
                "textura": "algodao gasto",
            },
        }
    )

    assert "peca principal: vestido azul indigio" in character["canonical_prompt"]
    assert "{'peca_principal'" not in character["canonical_prompt"]


def test_character_profile_infers_masculine_visual_gender() -> None:
    character = _character_profile({"name": "Lucas", "role": "filho"})

    assert character["gender"] == "personagem masculino"
    assert "Genero visual obrigatorio: masculino" in character["canonical_prompt"]
    assert "nao feminilizar" in character["canonical_prompt"]


def test_character_defaults_are_distinct_by_name() -> None:
    clara = _character_profile("Clara")
    lucas = _character_profile("Lucas")

    assert clara["base_outfit"] != lucas["base_outfit"]
    assert clara["hair"] != lucas["hair"]
    assert "nao reutilizar roupa" in " ".join(clara["visual_constraints"])


def test_character_initial_reference_uses_full_body_gray_background() -> None:
    character = _character_profile({"name": "Dona Celia"})

    prompt = visual_reference_prompt(character, "front_portrait")

    assert "personagem em pe" in prompt
    assert "corpo inteiro" in prompt
    assert "fundo cinza neutro de estudio" in prompt
    assert "sem cortar cabeca, pes ou maos" in prompt
    assert "Proporcao obrigatoria: 9:16" in prompt
    assert "referencia de continuidade para storyboard e video" in prompt


def test_character_multi_view_references_use_white_background_and_angles() -> None:
    character = _character_profile({"name": "Dona Celia"})

    prompt = visual_reference_prompt(character, "left_profile")

    assert "fundo branco puro de estudio" in prompt
    assert "vista lateral esquerda de corpo inteiro" in prompt
    assert "angulos diferentes" in prompt
    assert "mantendo exatamente o mesmo rosto" in prompt
    assert "Proporcao obrigatoria: 16:9" in prompt


def test_location_reference_prompt_forbids_people() -> None:
    location = _location_profile({"name": "Sala de estar"})

    prompt = visual_reference_prompt(location, "establishing")

    assert "Cenario vazio obrigatorio" in prompt
    assert "nao incluir pessoas" in prompt
    assert "sem personagens" in prompt
    assert "Proporcao obrigatoria: 16:9" in prompt


def test_prop_reference_prompt_requires_white_background_and_object_focus() -> None:
    prop = _prop_profile({"name": "Partitura", "material": "papel envelhecido"})

    prompt = visual_reference_prompt(prop, "front")

    assert "fundo branco puro" in prompt
    assert "objeto inteiro e centralizado" in prompt
    assert "sem pessoas" in prompt
    assert "sem maos" in prompt
    assert "Proporcao obrigatoria: 1:1" in prompt
    assert "detalhes principais legiveis" in prompt


def test_visual_reference_aspect_ratio_matches_asset_type_and_view() -> None:
    character = _character_profile({"name": "Dona Celia"})
    location = _location_profile({"name": "Sala de estar"})
    prop = _prop_profile({"name": "Partitura"})

    assert visual_reference_aspect_ratio(character, "front_portrait") == "9:16"
    assert visual_reference_aspect_ratio(character, "left_profile") == "16:9"
    assert visual_reference_aspect_ratio(location, "establishing") == "16:9"
    assert visual_reference_aspect_ratio(prop, "front") == "1:1"


def test_profile_items_accepts_mapping_sections_from_story_bible() -> None:
    items = _profile_items(
        {
            "protagonist": {"nome": "Clara", "funcao": "filha"},
            "mentor": "Mae de Clara",
        }
    )

    assert items == [
        {"nome": "Clara", "funcao": "filha", "name": "Clara"},
        {"name": "Mae de Clara", "description": "Mae de Clara"},
    ]


def test_profile_items_do_not_turn_internal_fields_into_cards() -> None:
    items = _profile_items(
        {
            "arc_aceita_que_o_legado_nao_e_perfeito": "arco emocional interno",
            "personality_teimosa_afetuosa": "personalidade interna",
            "palette_caracteristicas_visuais": ["azul", "branco"],
        }
    )

    assert len(items) == 1
    assert items[0]["name"] == "Item"
    assert "arc_aceita_que_o_legado_nao_e_perfeito" in items[0]


def test_profile_items_skip_internal_field_strings_inside_lists() -> None:
    items = _profile_items(
        [
            {"name": "Dona Lourdes", "role": "protagonista"},
            "palette_characteristicais_visuals_para_o_personagem",
            "personality_teimosa_afetuosa",
            "arc_aceita_que_o_legado_nao_e_controle",
        ]
    )

    assert items == [{"name": "Dona Lourdes", "role": "protagonista"}]


def test_profile_items_uses_named_mapping_keys_as_asset_names() -> None:
    items = _profile_items(
        {
            "dona_celia": {"role": "matriarca", "arc": "aceita o legado"},
            "lucas": {"role": "neto", "personality": "curioso"},
        }
    )

    assert [item["name"] for item in items] == ["Dona Celia", "Lucas"]
    assert items[0]["role"] == "matriarca"


def test_payload_section_accepts_portuguese_story_bible_keys() -> None:
    payload = {
        "personagens": [{"name": "Dona Celia"}],
        "locais": [{"name": "Sala de estar"}],
        "objetos": [{"name": "Partitura"}],
    }

    assert _payload_section(payload, ("characters", "personagens")) == payload["personagens"]
    assert _payload_section(payload, ("locations", "locais")) == payload["locais"]
    assert _payload_section(payload, ("props", "objetos")) == payload["objetos"]


def test_payload_section_accepts_nested_visual_bible_keys() -> None:
    payload = {
        "visual_bible": {
            "locais": {"quintal": {"layout": "fundo da casa"}},
            "objetos": {"partitura": {"material": "papel envelhecido"}},
        }
    }

    locations = _profile_items(_payload_section(payload, ("locations", "locais")))
    props = _profile_items(_payload_section(payload, ("props", "objetos")))

    assert locations[0]["name"] == "Quintal"
    assert props[0]["name"] == "Partitura"


def test_script_fallback_extracts_locations_and_props() -> None:
    script = """
    FADE IN:

    INT. COZINHA DE DONA LOURDES - MANHA
    Vapor sobe de uma panela de ferro preto. Ela mexe com uma colher de pau.

    EXT. QUINTAL - NOITE
    A neta segura uma carta amarelada.
    """

    locations = _script_location_profiles(script)
    props = _script_prop_profiles(script)

    assert [item["name"] for item in locations] == ["Cozinha De Dona Lourdes", "Quintal"]
    assert "Panela De Ferro Preto" in [item["name"] for item in props]
    assert "Carta Amarelada" in [item["name"] for item in props]


def test_script_fallback_repairs_missing_character_names() -> None:
    script = """
    INT. COZINHA - MANHA
    DONA LOURDES (88) mexe a panela.

    DONA LOURDES
    Agora e seu.

    NETE
    Eu prometo.
    """
    items = [{"name": "Item", "role": "protagonista"}, {"role": "neta"}]

    assert _script_character_names(script) == ["Dona Lourdes", "Nete"]
    assert [item["name"] for item in _repair_missing_character_names(items, script)] == [
        "Dona Lourdes",
        "Nete",
    ]


def test_script_fallback_does_not_partially_misname_character_cards() -> None:
    script = """
    INT. CASA - DIA
    CLARA encontra uma carta.

    CLARA
    Eu preciso saber a verdade.
    """
    items = [
        {"name": "Item", "role": "Protagonista"},
        {"name": "Item", "role": "Netinho (co-protagonista)"},
        {"name": "Item", "role": "Filha (coadjuvante)"},
    ]

    repaired = _repair_missing_character_names(items, script, "Dona Gertrudes")

    assert [item["name"] for item in repaired] == ["Dona Gertrudes", "Netinho", "Filha"]


def test_character_profile_uses_role_as_name_when_ai_omits_name() -> None:
    character = _character_profile({"role": "Netinho (co-protagonista)", "apparent_age": "16"})

    assert character["name"] == "Netinho"


@pytest.mark.asyncio
async def test_update_visual_target_prompt_versions_character_profile() -> None:
    project_id = uuid4()
    character_id = uuid4()
    artifact_id = uuid4()
    character = Character(
        id=character_id,
        project_id=project_id,
        artifact_id=artifact_id,
        name="Clara",
        role="protagonista",
        canonical_profile={"name": "Clara", "canonical_prompt": "Clara original"},
        character_fingerprint={},
        current_version=1,
    )

    class FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.committed = False
            self.refreshed: object | None = None

        async def get(self, model: type[object], item_id: object) -> object | None:
            if model is Character and item_id == character_id:
                return character
            if model is Artifact and item_id == artifact_id:
                return None
            return None

        def add(self, item: object) -> None:
            self.added.append(item)

        async def commit(self) -> None:
            self.committed = True

        async def refresh(self, item: object) -> None:
            self.refreshed = item

    session = FakeSession()

    updated = await update_visual_target_prompt(
        session,  # type: ignore[arg-type]
        project_id,
        "character",
        character_id,
        "Clara com jaqueta vermelha, rosto consistente",
    )

    assert updated is character
    assert character.current_version == 2
    assert character.canonical_profile["canonical_prompt"] == (
        "Clara com jaqueta vermelha, rosto consistente"
    )
    assert character.character_fingerprint["canonical_prompt"] == (
        "Clara com jaqueta vermelha, rosto consistente"
    )
    assert any(isinstance(item, CharacterVersion) for item in session.added)
    assert session.committed is True
    assert session.refreshed is character


@pytest.mark.asyncio
async def test_regenerate_visual_reference_forces_existing_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    target_id = uuid4()
    reference = object()
    captured: dict[str, Any] = {}

    async def fake_generate_visual_references(*args: object, **kwargs: object) -> list[object]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return [reference]

    monkeypatch.setattr(
        visual_bible_service,
        "generate_visual_references",
        fake_generate_visual_references,
    )

    result = await regenerate_visual_reference(
        object(),  # type: ignore[arg-type]
        project_id,
        "character",
        target_id,
        "front_portrait",
    )

    assert result is reference
    assert captured["args"][1:5] == (
        project_id,
        "character",
        target_id,
        ["front_portrait"],
    )
    assert captured["kwargs"] == {"force": True}
