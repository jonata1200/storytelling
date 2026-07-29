from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects.search import search_projects
from app.storytelling.search import search_story_ideas
from app.ui.search_filters import (
    filter_by_query,
    filter_ideas,
    filter_projects,
    has_idea_filters,
    has_project_filters,
    idea_complexity_bucket,
    item_matches_query,
    normalize_search_text,
    project_stage,
    project_status_bucket,
    read_field,
    safe_datetime,
    sort_by_datetime,
    sort_by_number,
    sort_by_text,
)


@dataclass
class Item:
    title: str | None
    created_at: object = None
    score: object = None


@dataclass
class ProjectItem:
    title: str
    description: str | None
    status: object
    created_at: object
    updated_at: object


def test_normalize_search_text_removes_accents_case_and_extra_spaces() -> None:
    assert normalize_search_text("  Ficção   CIENTÍFICA  ") == "ficcao cientifica"


def test_read_field_supports_objects_and_nested_dicts() -> None:
    item = {"project": {"title": "Cidade Invisível"}}

    assert read_field(item, "project.title") == "Cidade Invisível"
    assert read_field(Item(title="Roteiro"), "title") == "Roteiro"
    assert read_field(item, "project.missing") is None


def test_item_matches_query_uses_all_terms_across_multiple_fields() -> None:
    idea = {
        "title": "Cidade Invisível",
        "hook": "Uma criança encontra um mapa secreto",
        "protagonist": "Lia",
    }

    assert item_matches_query(idea, "cidade mapa", ["title", "hook", "protagonist"])
    assert item_matches_query(idea, "lia invisivel", ["title", "hook", "protagonist"])
    assert not item_matches_query(idea, "cidade oceano", ["title", "hook", "protagonist"])


def test_filter_by_query_returns_all_items_for_empty_query() -> None:
    items = [{"title": "A"}, {"title": "B"}]

    assert filter_by_query(items, "", ["title"]) == items


def test_filter_by_query_matches_partial_terms_without_accents() -> None:
    items = [
        {"title": "Mercado Noturno", "premise": "Drama urbano"},
        {"title": "Nave Silenciosa", "premise": "Ficção científica"},
    ]

    result = filter_by_query(items, "ficcao cien", ["title", "premise"])

    assert result == [items[1]]


def test_safe_datetime_parses_iso_strings_and_normalizes_timezone() -> None:
    parsed = safe_datetime("2026-07-29T10:00:00Z")

    assert parsed == datetime(2026, 7, 29, 10, tzinfo=UTC)
    assert safe_datetime("not-a-date") is None


def test_sort_by_datetime_keeps_missing_dates_last() -> None:
    items = [
        Item("sem data"),
        Item("antigo", "2026-01-01T00:00:00+00:00"),
        Item("novo", "2026-02-01T00:00:00+00:00"),
    ]

    assert [item.title for item in sort_by_datetime(items, "created_at")] == [
        "novo",
        "antigo",
        "sem data",
    ]


def test_sort_by_text_is_accent_insensitive_and_keeps_missing_values_last() -> None:
    items = [Item("Órbita"), Item(None), Item("Arco")]

    assert [item.title for item in sort_by_text(items, "title")] == ["Arco", "Órbita", None]


def test_sort_by_number_supports_descending_and_missing_values() -> None:
    items = [Item("baixo", score=2), Item("sem nota"), Item("alto", score="9")]

    assert [item.title for item in sort_by_number(items, "score", descending=True)] == [
        "alto",
        "baixo",
        "sem nota",
    ]


def test_filter_projects_combines_query_status_stage_period_and_sort() -> None:
    projects = [
        ProjectItem(
            title="Mercado Noturno",
            description="Drama urbano",
            status="VIDEO_GENERATION",
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-07-28T00:00:00+00:00",
        ),
        ProjectItem(
            title="Nave Solar",
            description="Ficção científica",
            status="COMPLETED",
            created_at="2026-02-01T00:00:00+00:00",
            updated_at="2026-06-01T00:00:00+00:00",
        ),
        ProjectItem(
            title="Roteiro Antigo",
            description="Drama urbano",
            status="SCRIPT_GENERATION",
            created_at="2026-03-01T00:00:00+00:00",
            updated_at="2026-05-01T00:00:00+00:00",
        ),
    ]

    result = filter_projects(
        projects,
        query="mercado drama",
        status_filter="active",
        stage_filter="video",
        updated_period="7",
        sort="title_asc",
        now=datetime(2026, 7, 29, tzinfo=UTC),
    )

    assert result == [projects[0]]
    assert project_status_bucket(projects[1]) == "done"
    assert project_stage(projects[2]) == "script"


def test_has_project_filters_detects_non_default_state() -> None:
    assert not has_project_filters("", "all", "all", "any", "updated_desc")
    assert has_project_filters("mercado", "all", "all", "any", "updated_desc")
    assert has_project_filters("", "review", "all", "any", "updated_desc")


def test_filter_ideas_combines_query_filters_and_sorting() -> None:
    ideas = [
        {
            "title": "Cidade Invisível",
            "theme": "memória",
            "hook": "Uma menina encontra uma porta",
            "premise": "Drama familiar",
            "protagonist": "Lia",
            "genre": "Drama",
            "primary_emotion": "Esperança",
            "duration_minutes": 5,
            "retention_potential": 8,
            "cliche_risk": 2,
            "production_complexity": 3,
            "created_at": "2026-07-28T00:00:00+00:00",
        },
        {
            "title": "Orbita Final",
            "theme": "espaço",
            "hook": "Um piloto ouve a própria voz",
            "premise": "Ficção científica",
            "protagonist": "Caio",
            "genre": "Ficção científica",
            "primary_emotion": "Tensão",
            "duration_minutes": 5,
            "retention_potential": 9,
            "cliche_risk": 4,
            "production_complexity": 8,
            "created_at": "2026-07-29T00:00:00+00:00",
        },
    ]

    result = filter_ideas(
        ideas,
        query="menina porta",
        genre_filter="Drama",
        emotion_filter="Esperança",
        duration_filter=5,
        complexity_filter="low",
        sort="retention_desc",
    )

    assert result == [ideas[0]]
    assert idea_complexity_bucket(ideas[1]) == "high"


def test_filter_ideas_sorts_by_metrics_and_title() -> None:
    ideas = [
        {"title": "Zeta", "retention_potential": 5, "cliche_risk": 8, "production_complexity": 4},
        {"title": "Arco", "retention_potential": 9, "cliche_risk": 1, "production_complexity": 2},
    ]

    assert [item["title"] for item in filter_ideas(ideas, sort="retention_desc")] == [
        "Arco",
        "Zeta",
    ]
    assert [item["title"] for item in filter_ideas(ideas, sort="title_asc")] == [
        "Arco",
        "Zeta",
    ]


def test_has_idea_filters_detects_non_default_state() -> None:
    assert not has_idea_filters("", "all", "all", "all", "all", "created_desc")
    assert has_idea_filters("", "Drama", "all", "all", "all", "created_desc")
    assert has_idea_filters("", "all", "all", 5, "all", "created_desc")


class _FakeScalarRows:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def scalars(self) -> "_FakeScalarRows":
        return self

    def __iter__(self) -> Any:
        return iter(self.rows)


class _FakeProjectSearchSession:
    def __init__(self, rows: list[Any], total: int) -> None:
        self.rows = rows
        self.total = total
        self.scalar_statement = ""
        self.execute_statement = ""

    async def scalar(self, statement: Any) -> int:
        self.scalar_statement = str(statement)
        return self.total

    async def execute(self, statement: Any) -> _FakeScalarRows:
        self.execute_statement = str(statement)
        return _FakeScalarRows(self.rows)


@pytest.mark.asyncio
async def test_search_projects_returns_paginated_contract_from_backend_query() -> None:
    row = SimpleNamespace(title="Mercado Noturno")
    session = _FakeProjectSearchSession([row], total=12)

    items, total = await search_projects(
        cast(AsyncSession, session),
        query="mercado",
        status_filter="active",
        stage_filter="video",
        updated_period="30",
        sort="title_asc",
        limit=10,
        offset=5,
    )

    assert items == [row]
    assert total == 12
    assert "projects" in session.scalar_statement
    assert "OFFSET" in session.execute_statement.upper()


class _FakeStoryIdeaSearchSession:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    async def get(self, _model: Any, project_id: Any) -> Any:
        return SimpleNamespace(id=project_id, deleted_at=None)

    async def execute(self, _statement: Any) -> _FakeScalarRows:
        return _FakeScalarRows(self.rows)


@pytest.mark.asyncio
async def test_search_story_ideas_filters_payload_and_paginates() -> None:
    project_id = uuid4()
    first = SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        title="Cidade Invisível",
        hook="Uma menina abre uma porta",
        premise="Drama urbano",
        protagonist="Lia",
        retention_potential=8,
        cliche_risk=2,
        production_complexity=3,
        payload={
            "genre": "Drama",
            "primary_emotion": "Esperança",
            "duration_minutes": 5,
            "theme": "memória",
        },
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )
    second = SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        title="Orbita Final",
        hook="Um piloto ouve a propria voz",
        premise="Ficção científica",
        protagonist="Caio",
        retention_potential=9,
        cliche_risk=4,
        production_complexity=8,
        payload={
            "genre": "Ficção científica",
            "primary_emotion": "Tensão",
            "duration_minutes": 5,
            "theme": "espaço",
        },
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    session = _FakeStoryIdeaSearchSession([second, first])

    items, total = await search_story_ideas(
        cast(AsyncSession, session),
        project_id,
        query="menina porta",
        genre_filter="Drama",
        emotion_filter="Esperança",
        duration_filter="5",
        complexity_filter="low",
        limit=1,
        offset=0,
    )

    assert items == [first]
    assert total == 1
