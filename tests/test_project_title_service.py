"""Testes da padronização de títulos na camada de serviço (ponto único de escrita)."""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.core.title_case import clean_idea_title, standardize_title_case


async def _not_locked(_session: Any, _project_id: Any) -> bool:
    return False


def test_standardize_title_case_matches_ui_implementation() -> None:
    # Casos canônicos (mesmos do test_title_standardization.py) para garantir
    # que a implementação movida para app.core.title_case se comporta igual.
    assert standardize_title_case("O ÚLTIMO TREM") == "O Último Trem"
    assert standardize_title_case("O ÚLTIMO SINAL") == "O Último Sinal"
    assert standardize_title_case("uma comunidade em silêncio") == "Uma Comunidade em Silêncio"
    assert standardize_title_case("o trem das 6: a última viagem") == (
        "O Trem das 6: A Última Viagem"
    )
    assert standardize_title_case("TV e o mistério da UF perdida") == (
        "TV e o Mistério da UF Perdida"
    )
    assert standardize_title_case("") == ""


@pytest.mark.asyncio
async def test_create_project_standardizes_all_caps_title(monkeypatch: Any) -> None:
    # Brecha histórica do "O ÚLTIMO TREM": o título ALL-CAPS chegava cru ao
    # Project(). A padronização agora acontece no service (ponto único).
    created: dict[str, Any] = {}

    class FakeProject:
        def __init__(self, title: str, description: str) -> None:
            created["title"] = title
            created["description"] = description
            self.id = uuid4()
            self.title = title
            self.description = description
            self.current_version = 0

    versions: list[Any] = []

    class FakeProjectVersion:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)
            versions.append(self)

    async def fake_flush() -> None:
        return None

    async def fake_commit() -> None:
        return None

    async def fake_refresh(_obj: Any) -> None:
        return None

    from app.projects import service as project_service

    monkeypatch.setattr(project_service, "Project", FakeProject)
    monkeypatch.setattr(project_service, "ProjectVersion", FakeProjectVersion)
    session = SimpleNamespace(
        add=lambda _obj: None, flush=fake_flush, commit=fake_commit, refresh=fake_refresh
    )

    await project_service.create_project(
        session,  # type: ignore[arg-type]
        SimpleNamespace(title="O ÚLTIMO TREM", description=""),
    )

    assert created["title"] == "O Último Trem"


@pytest.mark.asyncio
async def test_sync_project_title_standardizes_raw_llm_title(monkeypatch: Any) -> None:
    # O sync de título do roteiro recebia o título cru do LLM (ALL-CAPS) e
    # gravava sem padronização — caminho real que gerou "O ÚLTIMO TREM".
    from app.projects import service as project_service

    updated: dict[str, str] = {}

    class FakeProject:
        id = uuid4()
        title = "projeto sem título"
        description = ""
        deleted_at = None
        current_version = 0

        def __init__(self) -> None:
            self.title = "projeto sem título"

    project = FakeProject()

    async def fake_get(_session: Any, _id: Any, **_kwargs: Any) -> FakeProject:
        return project

    async def fake_refresh(_obj: Any) -> None:
        return None

    class FakeProjectVersion:
        def __init__(self, **_kwargs: Any) -> None:
            pass

    session = SimpleNamespace(
        get=fake_get,
        add=lambda _obj: None,
        commit=lambda: None,
        refresh=fake_refresh,
    )

    async def fake_commit() -> None:
        updated["title"] = project.title

    session.commit = fake_commit  # type: ignore[method-assign]

    monkeypatch.setattr(project_service, "Project", lambda *a, **k: project)
    monkeypatch.setattr(project_service, "ProjectVersion", FakeProjectVersion)
    monkeypatch.setattr(project_service, "_project_title_is_locked", _not_locked)

    # project.title é atributo lido após a escrita — monkeypatch em get já
    # devolve a instância; a função grava em project.title.
    await project_service.sync_project_title(
        session,  # type: ignore[arg-type]
        project.id,
        "O ÚLTIMO TREM",
    )

    assert project.title == "O Último Trem"
    assert updated["title"] == "O Último Trem"


def test_clean_idea_title_matches_page_config_behavior() -> None:
    # A função da UI é um wrapper do módulo canônico — comportamento idêntico.
    assert clean_idea_title("IDEIA 02 - O TREM DAS SEIS") == "O Trem das Seis"
    assert clean_idea_title("") == "História sem título"