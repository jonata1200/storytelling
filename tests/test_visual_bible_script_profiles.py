# ruff: noqa: F401
import os
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.projects.models import Artifact
from app.providers.image.types import ImageGenerationRequest, ImageResult
from app.visual_bible import service as visual_bible_service
from app.visual_bible.models import Character, CharacterVersion, VisualReference
from app.visual_bible.service import (
    _character_profile,
    _generate_image_with_provider_fallback,
    _image_provider_for_project,
    _location_profile,
    _merge_profile_items,
    _payload_section,
    _profile_items,
    _prop_profile,
    _repair_missing_character_names,
    _script_character_names,
    _script_character_profiles,
    _script_location_profiles,
    _script_prop_profiles,
    _transient_image_provider_error,
    _visual_generation_reference_uris,
    default_views_for,
    generate_visual_references,
    initial_view_for,
    regenerate_visual_reference,
    update_visual_target_prompt,
    validated_visual_reference_views,
    visual_profile_validation_errors,
    visual_reference_aspect_ratio,
    visual_reference_prompt,
)


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


def test_script_fallback_cleans_hierarchical_and_repeated_locations() -> None:
    script = """
    INT. HOSPITAL - QUARTO - DIA
    Ian acorda.

    INT. BARRACA VAZIA - MEIA-NOITE
    O mercado vira.

    EXT. TELHADO DA CASA - NOITE
    A chuva cai.

    EXT. TELHADO - CONTINUACAO
    Ian encara o ceu.

    EXT. CEMITERIO - AMANHECER
    O sol aparece.

    EXT. JARDIM DO HOSPITAL - DIA
    O sol aparece.
    """

    locations = _script_location_profiles(script)

    assert [item["name"] for item in locations] == [
        "Quarto Do Hospital",
        "Barraca Vazia",
        "Telhado Da Casa",
        "Cemiterio",
        "Jardim Do Hospital",
    ]
    barraca = next(item for item in locations if item["name"] == "Barraca Vazia")
    assert barraca["scene_numbers"] == [2]
    assert barraca["evidence_text"] == ["INT. BARRACA VAZIA - MEIA-NOITE"]


def test_script_fallback_does_not_turn_screenplay_markers_into_characters() -> None:
    script = """
    INT. QUARTO DE IAN - DIA
    IAN (9 anos) desenha.

    OS PAIS DE IAN (40 anos) entram no quarto.

    PAI
    Isso precisa parar.

    MAE
    Ele esta cansado.

    EXT. PATIO DA ESCOLA - DIA
    Um MENINO se aproxima.

    MENINO
    O que voce desenha?

    PASSARO
    Desenhe mais.

    AVÔ DE IAN (70 anos) surge na lembranca.

    VOLTA AO PRESENTE.
    """

    assert _script_character_names(script) == ["Ian", "Pai", "Mae", "Passaro", "Avô De Ian"]


def test_script_fallback_trims_action_phrases_from_props() -> None:
    script = """
    O desenho e tosco, mas cheio de vida.
    Ian pega uma corda e ve a chave no chao.
    """

    props = _script_prop_profiles(script)
    names = [item["name"] for item in props]

    assert "Desenho" in names
    assert "Corda" in names
    assert "Chave" in names
    assert "Desenho E Tosco" not in names
    assert "Corda E Ve" not in names


def test_script_fallback_extracts_accented_props_without_substring_false_positives() -> None:
    script = """
    Omero acorda no quarto e olha para as esferas de vidro.
    Ele pega uma esfera azul-clara, depois guarda um pequeno frasco vazio.
    O velho aponta para um relogio na torre.
    Os espelhos que mostram cenas do passado cercam a barraca.
    """

    props = _script_prop_profiles(script)
    names = [item["name"] for item in props]

    assert "Corda" not in names
    assert "Esfera Azul" in names
    assert "Frasco Vazio" in names
    assert "Relogio" in names
    assert "Espelhos" in names
    assert not any(name.startswith("Esferas") for name in names)
    esfera = next(item for item in props if item["name"] == "Esfera Azul")
    assert esfera["scene_numbers"] == [1]
    assert "esfera azul-clara" in esfera["evidence_text"][0]


def test_script_fallback_keeps_temporal_character_variants_with_evidence() -> None:
    script = """
    CENA 01
    INT. MERCADO - NOITE
    OMERO (34) vende memorias.

    OMERO
    Eu lembro.

    CENA 02
    INT. QUARTO DE INFANCIA - DIA
    OMERO CRIANCA (8) segura uma esfera.

    OMERO CRIANCA
    Mae, nao quero esquecer.
    """

    profiles = _script_character_profiles(script)
    names = [item["name"] for item in profiles]

    assert "Omero" in names
    assert "Omero Crianca" in names
    omero = next(item for item in profiles if item["name"] == "Omero")
    child = next(item for item in profiles if item["name"] == "Omero Crianca")
    assert omero["scene_numbers"] == [1]
    assert child["scene_numbers"] == [2]


def test_visual_profiles_preserve_script_evidence_metadata() -> None:
    location = _location_profile(
        {
            "name": "Barraca Vazia",
            "scene_numbers": [6, 7],
            "evidence_text": ["INT. BARRACA VAZIA - MEIA-NOITE"],
            "importance": "recorrente",
        }
    )
    prop = _prop_profile(
        {
            "name": "Esfera Azul",
            "scene_numbers": [1],
            "evidence_text": ["Omero pega uma esfera azul-clara."],
            "importance": "principal",
        }
    )
    character = _character_profile(
        {
            "name": "Omero Criança",
            "scene_numbers": [9],
            "evidence_text": ["OMERO CRIANÇA (8) está no colo da mãe."],
            "importance": "pontual",
        }
    )

    assert location["scene_numbers"] == [6, 7]
    assert location["evidence_text"] == ["INT. BARRACA VAZIA - MEIA-NOITE"]
    assert location["importance"] == "recorrente"
    assert prop["scene_numbers"] == [1]
    assert prop["evidence_text"] == ["Omero pega uma esfera azul-clara."]
    assert prop["importance"] == "principal"
    assert character["scene_numbers"] == [9]
    assert character["evidence_text"] == ["OMERO CRIANÇA (8) está no colo da mãe."]
    assert character["importance"] == "pontual"


def test_script_fallback_extracts_musical_props_from_script() -> None:
    script = """
    EXT. JARDIM DAS SOMBRAS - NOITE
    LUNA segura uma flauta de madeira rachada.
    Ela traz um violino improvisado, feito de galhos e cordas de tripa.
    Depois constrói um tambor de tronco oco e um chocalho de pedras.
    O JARDINEIRO mostra um cachimbo de osso, rachado, mudo.
    """

    props = _script_prop_profiles(script)

    assert "Flauta De Madeira Rachada" in [item["name"] for item in props]
    assert "Violino Improvisado" in [item["name"] for item in props]
    assert "Tambor De Tronco Oco" in [item["name"] for item in props]
    assert "Chocalho De Pedras" in [item["name"] for item in props]
    assert "Cachimbo De Osso" in [item["name"] for item in props]


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


def test_script_fallback_extracts_character_profiles_from_dialogue_and_action() -> None:
    script = """
    LUNA (17 anos, cega) segura uma flauta.

    Seu AVÔ (70 anos) segura seu braço.

    O JARDINEIRO DAS SOMBRAS (sem rosto) emerge do jardim.

    JARDINEIRO
    Silencio.

    UMA MULHER (50 anos)
    Ela traz mau agouro.
    """

    profiles = _script_character_profiles(script)

    assert [item["name"] for item in profiles] == [
        "Luna",
        "Avô",
        "Jardineiro Das Sombras",
        "Uma Mulher",
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
        "character_reference_sheet",
    )

    assert result is reference
    assert captured["args"][1:5] == (
        project_id,
        "character",
        target_id,
        ["character_reference_sheet"],
    )
    assert captured["kwargs"] == {"force": True}


@pytest.mark.asyncio
async def test_generate_visual_references_reloads_created_rows_without_refresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    target_id = uuid4()
    target_artifact_id = uuid4()

    class FakeRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def get_project(self, requested_project_id: object) -> object | None:
            return object() if requested_project_id == project_id else None

    class FakeScalarResult:
        def __init__(self, items: list[VisualReference]) -> None:
            self.items = items

        def __iter__(self) -> Any:
            return iter(self.items)

    class FakeResult:
        def __init__(self, items: list[VisualReference]) -> None:
            self.items = items

        def scalars(self) -> FakeScalarResult:
            return FakeScalarResult(self.items)

    class FakeSession:
        def __init__(self) -> None:
            self.added: list[Any] = []
            self.committed = False
            self.refreshed = False

        def add(self, item: object) -> None:
            self.added.append(item)

        async def flush(self) -> None:
            for item in self.added:
                if getattr(item, "id", None) is None:
                    item.id = uuid4()

        async def commit(self) -> None:
            self.committed = True

        async def execute(self, statement: object) -> FakeResult:
            return FakeResult([item for item in self.added if isinstance(item, VisualReference)])

        async def refresh(self, item: object) -> None:
            self.refreshed = True
            raise AssertionError("generate_visual_references should not refresh references")

    async def fake_target(*args: object, **kwargs: object) -> tuple[dict[str, str], object]:
        return (
            {"name": "Clara", "canonical_prompt": "Clara original"},
            target_artifact_id,
        )

    async def fake_provider(*args: object, **kwargs: object) -> tuple[object, str, str]:
        return object(), "mock-image", "mock_images"

    async def fake_production_settings(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(image_resolution="1080x1920")

    async def fake_image(
        provider: object, request: ImageGenerationRequest
    ) -> tuple[ImageResult, dict]:
        return (
            ImageResult(
                file_path=tmp_path / "front.svg",
                storage_uri="storage://front.svg",
                sha256="abc",
                content_type="image/svg+xml",
                provider="mock",
                model="mock-image",
                prompt=request.prompt,
            ),
            {},
        )

    async def fake_add_dependency(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(visual_bible_service, "ProjectRepository", FakeRepository)
    monkeypatch.setattr(visual_bible_service, "_get_visual_target", fake_target)
    monkeypatch.setattr(visual_bible_service, "_image_provider_for_project", fake_provider)
    monkeypatch.setattr(
        visual_bible_service,
        "get_or_create_production_settings",
        fake_production_settings,
    )
    monkeypatch.setattr(
        visual_bible_service,
        "_generate_image_with_provider_fallback",
        fake_image,
    )
    monkeypatch.setattr(visual_bible_service, "_add_dependency", fake_add_dependency)

    session = FakeSession()

    references = await generate_visual_references(
        session,  # type: ignore[arg-type]
        project_id,
        "character",
        target_id,
        ["character_reference_sheet"],
        force=True,
    )

    assert session.committed is True
    assert session.refreshed is False
    assert references is not None
    assert len(references) == 1
    assert references[0].view_type == "character_reference_sheet"
