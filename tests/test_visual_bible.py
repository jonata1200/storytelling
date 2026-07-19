from uuid import uuid4

import pytest

from app.projects.models import Artifact
from app.visual_bible import service as visual_bible_service
from app.visual_bible.models import Character, CharacterVersion
from app.visual_bible.service import (
    _character_profile,
    _location_profile,
    _payload_section,
    _profile_items,
    _prop_profile,
    default_views_for,
    initial_view_for,
    regenerate_visual_reference,
    update_visual_target_prompt,
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


def test_visual_reference_prompt_uses_canonical_profile_prompt() -> None:
    profile = {
        "name": "Helena",
        "canonical_prompt": "Helena, 35, expressive detective, rainy noir lighting",
    }

    assert (
        visual_reference_prompt(profile, "front_portrait")
        == "Helena, 35, expressive detective, rainy noir lighting. Vista de referencia: "
        "front_portrait. retrato frontal, rosto centralizado, expressao neutra, camera na "
        "altura dos olhos. Referencia de producao vertical 9:16, fundo limpo, identidade "
        "visual consistente."
    )


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
        "Referencia profissional de design cinematografico de personagem"
        in character["canonical_prompt"]
    )
    assert "cabelo castanho curto" in character["canonical_prompt"]
    assert "continuidade de figurino" in character["canonical_prompt"]
    assert (
        "Referencia profissional de design cinematografico de cenario"
        in location["canonical_prompt"]
    )
    assert "geografia segura para camera" in location["canonical_prompt"]
    assert "Referencia profissional de design cinematografico de objeto" in prop["canonical_prompt"]
    assert "papel amassado" in prop["canonical_prompt"]


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
    payload = {"visual_bible": {"locais": [{"name": "Quintal"}]}}

    assert _payload_section(payload, ("locations", "locais")) == [{"name": "Quintal"}]


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
    captured: dict[str, object] = {}

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
