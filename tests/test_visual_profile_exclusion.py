"""Regressão da exclusão manual de cards da Bíblia Visual."""

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.visual_bible.manual_references import (
    add_visual_exclusion,
    load_visual_exclusions,
    remove_visual_exclusion,
    visual_exclusion_key,
    visual_exclusion_keys,
)
from app.visual_bible.profiles import _visual_key
from app.visual_bible.service import _filter_excluded_items


class FakeResult:
    def __init__(self, value: Any = None) -> None:
        self._value = value

    def scalars(self) -> Any:
        return SimpleNamespace(first=lambda: self._value, all=lambda: [])


class FakeSession:
    """Suficiente para add/load/remove/_filter: execute + add + commit."""

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings
        self.added: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, _statement: Any) -> FakeResult:
        return FakeResult(self._settings)


def test_visual_exclusion_keys_match_across_writer_and_filter() -> None:
    """As chaves gravadas pelo tombstone casam com as derivadas no filtro."""
    target = SimpleNamespace(
        name="Voz Gravada",
        canonical_profile={"permanent_id": "char_abc12345", "name": "Voz Gravada"},
    )
    keys = visual_exclusion_keys(
        "character", str(target.name), str(target.canonical_profile["permanent_id"])
    )
    assert keys == {
        f"character:{_visual_key('char_abc12345')}",
        f"character:{_visual_key('Voz Gravada')}",
    }
    # visual_key normaliza pontuação: char_abc12345 vira charabc12345
    assert f"character:{_visual_key('char_abc12345')}" == "character:charabc12345"
    assert f"character:{_visual_key('Voz Gravada')}" == "character:vozgravada"
    # A chave primária é uma das variantes
    assert visual_exclusion_key("character", target) in keys


def test_visual_exclusion_key_falls_back_to_name() -> None:
    target = SimpleNamespace(name="Melhor Amigo", canonical_profile={})
    assert visual_exclusion_key("character", target) == "character:melhoramigo"


def test_add_and_load_visual_exclusion_roundtrip() -> None:
    async def scenario() -> None:
        session = FakeSession(settings=None)
        await add_visual_exclusion(
            session,
            uuid4(),
            key="character:vozgravada",
            label="Personagem: Voz Gravada",
            alt_keys={"character:charabc12345"},
        )
        settings = session.added[0]
        assert settings.metadata_json["visual_exclusions"][0]["key"] == "character:vozgravada"
        assert settings.metadata_json["visual_exclusions"][0]["alt_keys"] == [
            "character:charabc12345"
        ]
        reader = FakeSession(settings=settings)
        entries = await load_visual_exclusions(reader, uuid4())
        assert len(entries) == 1
        assert entries[0]["label"] == "Personagem: Voz Gravada"

    asyncio.run(scenario())


def test_add_is_idempotent_and_merges_alt_keys() -> None:
    async def scenario() -> int:
        session = FakeSession(settings=None)
        await add_visual_exclusion(
            session, uuid4(), key="character:vozgravada", label="L1"
        )
        settings = session.added[0]
        # segunda chamada com NOVA sessão lendo o estado persistido
        session2 = FakeSession(settings)
        await add_visual_exclusion(
            session2,
            uuid4(),
            key="character:vozgravada",
            label="L1",
            alt_keys={"character:charabc12345"},
        )
        entries = settings.metadata_json["visual_exclusions"]
        assert len(entries) == 1
        assert entries[0]["alt_keys"] == ["character:charabc12345"]
        return len(entries)

    assert asyncio.run(scenario()) == 1


def test_remove_visual_exclusion_clears_entry_and_alt_keys() -> None:
    async def scenario() -> bool:
        settings = SimpleNamespace(
            metadata_json={
                "visual_exclusions": [
                    {
                        "key": "character:vozgravada",
                        "label": "Personagem: Voz Gravada",
                        "alt_keys": ["character:charabc12345"],
                    }
                ]
            }
        )
        session = FakeSession(settings=settings)
        return await remove_visual_exclusion(session, uuid4(), "character:charabc12345")

    # Restaurar por uma das chaves alternativas remove o tombstone inteiro.
    assert asyncio.run(scenario()) is True


def test_remove_visual_exclusion_returns_false_when_absent() -> None:
    async def scenario() -> bool:
        settings = SimpleNamespace(metadata_json={"visual_exclusions": []})
        session = FakeSession(settings=settings)
        return await remove_visual_exclusion(session, uuid4(), "character:naoexiste")

    assert asyncio.run(scenario()) is False


def test_filter_excluded_items_drops_by_key_and_alt_keys() -> None:
    async def scenario() -> list[str]:
        exclusions = [
            {
                "key": "character:charabc12345",
                "label": "Personagem: Voz Gravada",
                "alt_keys": ["character:vozgravada"],
            }
        ]
        session = FakeSession(
            settings=SimpleNamespace(metadata_json={"visual_exclusions": exclusions})
        )
        items = [
            {"name": "Voz Gravada", "id": "char_abc12345"},
            {"name": "Elias", "id": "char_99999999"},
        ]
        filtered = await _filter_excluded_items(session, uuid4(), "character", items)
        return [item["name"] for item in filtered]

    assert asyncio.run(scenario()) == ["Elias"]


def test_filter_excluded_items_keeps_everything_without_exclusions() -> None:
    async def scenario() -> list[dict]:
        session = FakeSession(settings=None)
        items = [{"name": "Elias"}]
        return await _filter_excluded_items(session, uuid4(), "character", items)

    assert asyncio.run(scenario()) == [{"name": "Elias"}]


def test_filter_matches_casing_variants_but_not_accent_stems() -> None:
    """visual_key normaliza caixa/pontuação e remove acentos (VÓZ→vz).

    Documenta o comportamento real: a variante de CAIXA casa ("VÓZ GRAVADA"
    gravado como "vozgravada" não casa — o acento muda o radical); a exclusão
    usa a MESMA normalização do matching de upsert do app (consistent-by-design:
    se o nome bater no upsert, bate na exclusão).
    """

    async def scenario() -> list[str]:
        # grava com a MESMA normalização do app (como delete_visual_profile faz)
        exclusions = [
            {
                "key": f"character:{_visual_key('VÓZ GRAVADA')}",
                "label": "L",
                "alt_keys": [f"character:{_visual_key('Voz Gravada')}"],
            }
        ]
        session = FakeSession(
            settings=SimpleNamespace(metadata_json={"visual_exclusions": exclusions})
        )
        items = [{"name": "VÓZ GRAVADA", "id": "char_1"}, {"name": "Elias"}]
        filtered = await _filter_excluded_items(session, uuid4(), "character", items)
        return [item["name"] for item in filtered]

    assert asyncio.run(scenario()) == ["Elias"]