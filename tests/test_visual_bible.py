import os
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.config.settings import Settings
from app.providers.image.types import ImageGenerationRequest
from app.visual_bible import service as visual_bible_service
from app.visual_bible.script_profiles import _script_location_profiles
from app.visual_bible.service import (
    _character_profile,
    _generate_image_with_provider_fallback,
    _image_provider_for_project,
    _location_profile,
    _merge_profile_items,
    _payload_section,
    _profile_items,
    _prop_profile,
    _transient_image_provider_error,
    _visual_generation_reference_uris,
    default_views_for,
    initial_view_for,
    validated_visual_reference_views,
    visual_profile_validation_errors,
    visual_reference_aspect_ratio,
    visual_reference_prompt,
)


def test_default_character_views_include_required_reference_sheet_items() -> None:
    views = default_views_for("character")

    assert views == ["front_portrait", "character_reference_sheet"]


def test_sourceful_502_is_treated_as_transient_image_provider_error() -> None:
    error = RuntimeError("OmniRoute Images HTTP 502: provider returned an internal error")

    assert _transient_image_provider_error(error) is True


@pytest.mark.asyncio
async def test_image_generation_errors_are_reported_without_mock_fallback(
    tmp_path: Path,
) -> None:
    class FailingGoogleProvider:
        provider_name = "google_ai"

        async def generate(self, request: ImageGenerationRequest) -> object:
            raise RuntimeError("Google AI Images HTTP 502: provider returned an internal error")

    with pytest.raises(RuntimeError, match="Google AI Images HTTP 502"):
        await _generate_image_with_provider_fallback(
            FailingGoogleProvider(),  # type: ignore[arg-type]
            ImageGenerationRequest(
                prompt="Personagem em pe, vista frontal",
                target_id="character-1",
                view_type="character_reference_sheet",
                output_dir=tmp_path,
                model="gemini-3.1-flash-lite-image",
            ),
        )

    assert os.listdir(tmp_path) == []


@pytest.mark.asyncio
async def test_image_provider_uses_real_default_model_instead_of_project_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()

    async def fake_settings(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(image_model="mock-image")

    monkeypatch.setattr(
        visual_bible_service,
        "get_settings",
        lambda: SimpleNamespace(
            ai_provider="ollama_cloud",
            image_provider="google_ai",
            google_ai_image_model="gemini-3.1-flash-lite-image",
        ),
    )
    monkeypatch.setattr(
        visual_bible_service,
        "get_or_create_production_settings",
        fake_settings,
    )

    provider, model, directory = await _image_provider_for_project(
        object(),  # type: ignore[arg-type]
        project_id,
    )

    assert getattr(provider, "provider_name", None) == "google_ai"
    assert model == "gemini-3.1-flash-lite-image"
    assert directory == "google_ai_images"


@pytest.mark.asyncio
async def test_image_provider_uses_google_ai_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()

    async def fake_settings(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(image_model="mock-image")

    monkeypatch.setattr(
        visual_bible_service,
        "get_settings",
        lambda: Settings(
            ai_provider="ollama_cloud",
            image_provider="google_ai",
            google_ai_image_model="gemini-3.1-flash-lite-image",
        ),
    )
    monkeypatch.setattr(
        visual_bible_service,
        "get_or_create_production_settings",
        fake_settings,
    )

    provider, model, directory = await _image_provider_for_project(
        object(),  # type: ignore[arg-type]
        project_id,
    )

    assert getattr(provider, "provider_name", None) == "google_ai"
    assert model == "gemini-3.1-flash-lite-image"
    assert directory == "google_ai_images"


@pytest.mark.asyncio
async def test_image_provider_maps_legacy_omniroute_preference_to_google_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_settings(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(image_model="mock-image")

    monkeypatch.setattr(
        visual_bible_service,
        "get_settings",
        lambda: SimpleNamespace(
            ai_provider="ollama_cloud",
            image_provider="omniroute",
            google_ai_image_model="gemini-3.1-flash-lite-image",
        ),
    )
    monkeypatch.setattr(
        visual_bible_service,
        "get_or_create_production_settings",
        fake_settings,
    )

    provider, model, directory = await _image_provider_for_project(
        object(),  # type: ignore[arg-type]
        uuid4(),
    )

    assert getattr(provider, "provider_name", None) == "google_ai"
    assert model == "gemini-3.1-flash-lite-image"
    assert directory == "google_ai_images"


def test_initial_visual_reference_is_single_canonical_view() -> None:
    assert initial_view_for("character") == "front_portrait"
    assert initial_view_for("location") == "establishing"
    assert initial_view_for("prop") == "front"

    for target_kind in ["character", "location", "prop"]:
        assert initial_view_for(target_kind) in default_views_for(target_kind)


def test_visual_reference_views_reject_invalid_values() -> None:
    assert validated_visual_reference_views("prop", ["front"]) == ["front"]

    with pytest.raises(ValueError, match="View type inválido"):
        validated_visual_reference_views("prop", ["prop_reference_sheet"])


def test_visual_reference_prompt_uses_canonical_profile_prompt() -> None:
    profile = {
        "name": "Helena",
        "canonical_prompt": "Helena, 35, expressive detective, rainy noir lighting",
    }

    prompt = visual_reference_prompt(profile, "character_reference_sheet")

    assert prompt.startswith(
        "Helena, 35, expressive detective, rainy noir lighting. Vista: folha única"
    )
    assert "perspectivas solicitadas" in prompt
    assert "Proporcao: 16:9" in prompt
    assert "sem texto" in prompt
    assert "Referência de continuidade" in prompt
    assert len(prompt) < 900


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

    assert "Fotorrealista, referência de elenco" in character["canonical_prompt"]
    assert "Manter mesmo rosto" in character["canonical_prompt"]
    assert character["narrative_profile"]["name"] == "Clara"
    assert character["gender"] == "personagem feminino"
    assert "Gênero visual obrigatório: feminino" in character["canonical_prompt"]
    assert "identidade consistente do personagem" in character["canonical_prompt"]
    assert "uma única péssoa" not in character["canonical_prompt"]
    assert character["visual_profile"]["hair"] == "cabelo castanho curto"
    assert "cabelo castanho curto" in character["canonical_prompt"]
    assert "Figurino base exclusivo" in character["canonical_prompt"]
    assert "Fotorrealista, fotografia de arquitetura" in location["canonical_prompt"]
    assert "ambiente vazio" in location["canonical_prompt"]
    assert "Nenhuma péssoa" in location["canonical_prompt"]
    assert "Fotorrealista, fotografia de produto" in prop["canonical_prompt"]
    assert "papel amassado" in prop["canonical_prompt"]
    assert location["narrative_profile"]["name"] == "Casa da familia"
    assert prop["visual_profile"]["material"] == "papel amassado"
    assert len(character["canonical_prompt"]) < 700
    assert len(location["canonical_prompt"]) < 560
    assert len(prop["canonical_prompt"]) < 480


def test_character_canonical_prompt_avoids_redundant_noun_repetition() -> None:
    character = _character_profile(
        {
            "name": "Helena",
            "role": "detetive",
            "face_shape": "rosto com estrutura clara e memoravel",
            "skin_tone": "tom de pele natural sob luz cinematica",
            "hair": "cabelo castanho curto, bem alinhado",
            "base_outfit": "figurino blazer cinza gasto",
            "palette": ["paleta terracota", "caramelo", "azul desbotado"],
        }
    )

    prompt = character["canonical_prompt"].lower()

    assert re.search(r"\brosto\s+rosto\b", prompt) is None
    assert re.search(r"\bcabelo\s+cabelo\b", prompt) is None
    assert re.search(r"\bpele\s+pele\b", prompt) is None
    assert re.search(r"\bfigurino\s+figurino\b", prompt) is None
    assert re.search(r"\bpaleta\s+paleta\b", prompt) is None
    assert "cabelo castanho curto" in prompt


def test_visual_profile_validation_rejects_generic_profiles() -> None:
    location = _location_profile({"name": "Local principal"})
    prop = _prop_profile({"name": "Objeto de revelacao"})

    assert "name generico: Local principal" in visual_profile_validation_errors(
        "location", location
    )
    assert "name generico: Objeto de revelacao" in visual_profile_validation_errors("prop", prop)


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
    assert "Gênero visual obrigatório: masculino" in character["canonical_prompt"]
    assert "não feminilizar" in character["canonical_prompt"]


def test_character_defaults_are_distinct_by_name() -> None:
    clara = _character_profile("Clara")
    lucas = _character_profile("Lucas")

    assert clara["base_outfit"] != lucas["base_outfit"]
    assert clara["hair"] != lucas["hair"]
    assert "não reutilizar roupa" in " ".join(clara["visual_constraints"])


def test_temporal_character_versions_share_visual_identity_defaults() -> None:
    omero = _character_profile({"name": "Omero", "role": "protagonista"})
    future_omero = _character_profile({"name": "Futuro Omero", "role": "protagonista"})

    assert omero["name"] == "Omero"
    assert future_omero["name"] == "Futuro Omero"
    assert omero["permanent_id"] != future_omero["permanent_id"]
    assert omero["identity_base_name"] == "Omero"
    assert future_omero["identity_base_name"] == "Omero"
    assert "versão futura" in future_omero["identity_variant_note"]
    for key in ("origin", "height_cm", "hair", "eyes", "body_type", "base_outfit", "palette"):
        assert future_omero[key] == omero[key]
    assert "Identidade visual base: Omero" in future_omero["canonical_prompt"]
    assert "Variante temporal" in future_omero["canonical_prompt"]


def test_character_initial_reference_uses_single_turnaround_sheet() -> None:
    character = _character_profile({"name": "Dona Celia"})

    prompt = visual_reference_prompt(character, "front_portrait")

    assert "imagem inicial do personagem em pe" in prompt
    assert "corpo inteiro" in prompt
    assert "vista frontal" in prompt
    assert "pose neutra" in prompt
    assert "fundo cinza neutro de estudio" in prompt
    assert "uma única péssoa" in prompt
    assert "não cortar cabeça, pés ou mãos" in prompt
    assert "Proporcao: 9:16" in prompt
    assert "Referência de continuidade" in prompt
    assert len(prompt) < 900


def test_character_approved_reference_sheet_uses_multiple_perspectives() -> None:
    character = _character_profile({"name": "Dona Celia"})

    prompt = visual_reference_prompt(character, "character_reference_sheet")

    assert "folha única de referência" in prompt
    assert "close frontal grande do rosto" in prompt
    assert "corpo inteiro frontal" in prompt
    assert "perfil lateral" in prompt
    assert "corpo inteiro de costas" in prompt
    assert "uma única imagem" in prompt
    assert "fundo branco puro de estudio" in prompt
    assert "não cortar cabeça, pés ou mãos" in prompt
    assert "Proporcao: 16:9" in prompt
    assert "Referência de continuidade" in prompt
    assert len(prompt) < 1100


def test_character_legacy_multi_view_prompt_is_still_supported_for_old_references() -> None:
    character = _character_profile({"name": "Dona Celia"})

    prompt = visual_reference_prompt(character, "left_profile")

    assert "fundo branco puro de estudio" in prompt
    assert "vista lateral esquerda de corpo inteiro" in prompt
    assert "angulo solicitado" in prompt
    assert "manter mesmo rosto" in prompt
    assert "Proporcao: 16:9" in prompt
    assert len(prompt) < 850


@pytest.mark.asyncio
async def test_character_generation_uses_front_and_related_identity_references() -> None:
    project_id = uuid4()
    target_id = uuid4()
    related_id = uuid4()
    current_asset_id = uuid4()
    related_asset_id = uuid4()
    now = datetime.now()
    current_reference = SimpleNamespace(
        asset_id=current_asset_id,
        view_type="front_portrait",
        created_at=now,
    )
    related_character = SimpleNamespace(
        id=related_id,
        canonical_profile={"identity_base_name": "Omero"},
    )
    related_reference = SimpleNamespace(
        asset_id=related_asset_id,
        view_type="front_portrait",
        created_at=now,
    )

    class FakeScalars:
        def __init__(self, items: list[object]) -> None:
            self.items = items

        def first(self) -> object | None:
            return self.items[0] if self.items else None

        def __iter__(self) -> Any:
            return iter(self.items)

    class FakeResult:
        def __init__(self, items: list[object]) -> None:
            self.items = items

        def scalars(self) -> FakeScalars:
            return FakeScalars(self.items)

    class FakeSession:
        def __init__(self) -> None:
            self.execute_calls = 0

        async def execute(self, statement: object) -> FakeResult:
            self.execute_calls += 1
            if self.execute_calls == 1:
                return FakeResult([current_reference])
            if self.execute_calls == 2:
                return FakeResult([related_character])
            return FakeResult([related_reference])

        async def get(self, model: object, asset_id: object) -> object:
            return SimpleNamespace(storage_uri=f"storage/ref-{asset_id}.png")

    references = await _visual_generation_reference_uris(
        FakeSession(),  # type: ignore[arg-type]
        project_id,
        "character",
        target_id,
        {"identity_base_name": "Omero"},
        "character_reference_sheet",
    )

    assert references == [
        f"storage/ref-{current_asset_id}.png",
        f"storage/ref-{related_asset_id}.png",
    ]


def test_location_reference_prompt_forbids_people() -> None:
    location = _location_profile({"name": "Sala de estar"})

    prompt = visual_reference_prompt(location, "establishing")

    assert "cenario vazio" in prompt
    assert "sem pessoas" in prompt
    assert "sem personagens" in prompt
    assert "Proporcao: 16:9" in prompt
    assert len(prompt) < 720


def test_script_location_profiles_split_composite_int_ext_sluglines() -> None:
    profiles = _script_location_profiles(
        "CENA 1\n"
        "INT. ATELIÊ DE HELENA / EXT. AEROPORTO - DIA (MONTAGEM)\n"
        "Helena fecha a porta enquanto Laura espera no embarque."
    )

    assert [item["name"] for item in profiles] == ["Aeroporto"]


def test_prop_reference_prompt_requires_white_background_and_object_focus() -> None:
    prop = _prop_profile({"name": "Partitura", "material": "papel envelhecido"})

    prompt = visual_reference_prompt(prop, "front")

    assert "vista frontal" in prompt
    assert "fundo branco puro" in prompt
    assert "sem pessoas" in prompt
    assert "sem mãos" in prompt
    assert "sem texto" in prompt
    assert "Proporcao: 1:1" in prompt
    assert "detalhes legíveis" in prompt
    assert len(prompt) < 700


def test_location_floor_plan_prompt_uses_technical_top_view() -> None:
    location = _location_profile({"name": "Sala de estar"})

    prompt = visual_reference_prompt(location, "floor_plan")

    assert "planta baixa limpa vista de cima" in prompt
    assert "sem perspectiva" in prompt
    assert "visual tecnico" in prompt
    assert "sem pessoas" in prompt
    assert "Proporcao: 16:9" in prompt


def test_visual_reference_aspect_ratio_matches_asset_type_and_view() -> None:
    character = _character_profile({"name": "Dona Celia"})
    location = _location_profile({"name": "Sala de estar"})
    prop = _prop_profile({"name": "Partitura"})

    assert visual_reference_aspect_ratio(character, "character_reference_sheet") == "16:9"
    assert visual_reference_aspect_ratio(character, "front_portrait") == "9:16"
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
            "arc_aceita_que_o_legado_não_e_perfeito": "arco emocional interno",
            "personality_teimosa_afetuosa": "personalidade interna",
            "palette_caracteristicas_visuais": ["azul", "branco"],
        }
    )

    assert len(items) == 1
    assert items[0]["name"] == "Item"
    assert "arc_aceita_que_o_legado_não_e_perfeito" in items[0]


def test_profile_items_skip_internal_field_strings_inside_lists() -> None:
    items = _profile_items(
        [
            {"name": "Dona Lourdes", "role": "protagonista"},
            "palette_characteristicais_visuals_para_o_personagem",
            "personality_teimosa_afetuosa",
            "arc_aceita_que_o_legado_não_e_controle",
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
