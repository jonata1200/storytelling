from pathlib import Path
from typing import NoReturn

import pytest

from app.config.settings import Settings
from app.providers.llm.types import LLMRequest, LLMResult
from app.storytelling import idea_lab
from app.storytelling.idea_lab import (
    delete_all_ideas,
    delete_generated_idea,
    delete_saved_idea,
    generate_freeform_ideas,
    load_generated_ideas,
    load_saved_ideas,
    replace_generated_ideas,
    save_idea,
)


@pytest.mark.asyncio
async def test_generate_freeform_ideas_returns_ten_ai_suggested_ideas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(idea_lab, "get_settings", lambda: Settings(openrouter_api_key=None))
    ideas = await generate_freeform_ideas(
        "uma memoria de infancia", count=10, target_duration_minutes=6
    )

    assert len(ideas) == 10
    assert all(idea.get("genre") for idea in ideas)
    assert all(idea.get("primary_emotion") for idea in ideas)
    assert {int(idea.get("duration_minutes", 0)) for idea in ideas} == {6}


@pytest.mark.asyncio
async def test_generate_freeform_ideas_respects_selected_genre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(idea_lab, "get_settings", lambda: Settings(openrouter_api_key=None))
    ideas = await generate_freeform_ideas(count=10, genre="Aventura")

    assert len(ideas) == 10
    assert {idea.get("genre") for idea in ideas} == {"Aventura"}


@pytest.mark.asyncio
async def test_generate_freeform_ideas_falls_back_when_openrouter_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingOpenRouterProvider:
        provider_name = "openrouter"

        async def generate_structured(self, request: object) -> NoReturn:
            raise RuntimeError("OpenRouter HTTP 429: rate limit")

    monkeypatch.setattr(
        idea_lab,
        "get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test", openrouter_default_model="free-model"),
    )
    monkeypatch.setattr(idea_lab, "OpenRouterLLMProvider", FailingOpenRouterProvider)

    ideas = await generate_freeform_ideas(count=3, genre="Suspense")

    assert len(ideas) == 3
    assert {idea.get("genre") for idea in ideas} == {"Suspense"}


@pytest.mark.asyncio
async def test_generate_freeform_ideas_retries_when_idea_contract_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidThenValidProvider:
        provider_name = "openrouter"

        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def generate_structured(self, request: LLMRequest) -> LLMResult:
            self.prompts.append(request.prompt)
            if len(self.prompts) == 1:
                content = {
                    "ideas": [
                        {
                            "title": "A porta verde",
                            "genre": "Suspense",
                            "primary_emotion": "Curiosidade",
                            "hook": "Uma porta aparece onde antes havia uma parede.",
                            "premise": (
                                "Uma zeladora encontra uma sala apagada da memoria do predio."
                            ),
                            "protagonist": "Nina, uma zeladora observadora",
                            "duration_minutes": 5,
                            "retention_potential": 80,
                            "cliche_risk": 20,
                            "production_complexity": 30,
                        }
                    ]
                }
            else:
                content = {
                    "ideas": [
                        {
                            "title": "A porta verde",
                            "genre": "Suspense",
                            "primary_emotion": "Curiosidade",
                            "theme": "memoria coletiva",
                            "hook": "Uma porta aparece onde antes havia uma parede.",
                            "premise": (
                                "Uma zeladora encontra uma sala apagada da memoria do predio."
                            ),
                            "protagonist": "Nina, uma zeladora observadora",
                            "conflict": "Abrir a sala pode devolver uma tragedia ao predio.",
                            "obstacles": ["medo dos moradores", "registros adulterados"],
                            "stakes": "O predio inteiro pode perder sua historia.",
                            "twist": "Nina foi quem pediu para apagar a sala.",
                            "climax": "Ela abre a porta durante uma reuniao dos moradores.",
                            "payoff": "A memoria volta como cuidado, nao como culpa.",
                            "resolution": "Os moradores transformam a sala em arquivo vivo.",
                            "duration_minutes": 5,
                            "retention_potential": 82,
                            "cliche_risk": 18,
                            "production_complexity": 34,
                        }
                    ]
                }
            return LLMResult(content=content, model=request.model, provider=self.provider_name)

    provider = InvalidThenValidProvider()
    monkeypatch.setattr(
        idea_lab,
        "get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test", openrouter_default_model="free-model"),
    )
    monkeypatch.setattr(idea_lab, "OpenRouterLLMProvider", lambda: provider)

    ideas = await generate_freeform_ideas(count=1, genre="Suspense")

    assert len(ideas) == 1
    assert ideas[0]["payoff"] == "A memoria volta como cuidado, nao como culpa."
    assert len(provider.prompts) == 2
    assert "campo obrigatorio vazio: conflict" in provider.prompts[1]


def test_saved_ideas_can_be_saved_and_deleted(tmp_path: Path) -> None:
    path = tmp_path / "saved-ideas.json"
    saved = save_idea(
        {
            "id": "idea-1",
            "title": "A chave no jardim",
            "genre": "Suspense",
            "primary_emotion": "Curiosidade",
        },
        path,
    )

    assert saved["id"] == "idea-1"
    assert load_saved_ideas(path)[0]["title"] == "A chave no jardim"

    delete_saved_idea("idea-1", path)

    assert load_saved_ideas(path) == []


def test_generated_ideas_can_be_persisted_and_discarded(tmp_path: Path) -> None:
    path = tmp_path / "generated-ideas.json"
    ideas = replace_generated_ideas(
        [
            {
                "id": "idea-pending-1",
                "title": "A ponte azul",
                "genre": "Aventura",
                "primary_emotion": "Coragem",
                "duration_minutes": 7,
            }
        ],
        path,
    )

    assert ideas[0]["id"] == "idea-pending-1"
    assert ideas[0]["duration_minutes"] == 7
    assert load_generated_ideas(path)[0]["title"] == "A ponte azul"

    delete_generated_idea("idea-pending-1", path)

    assert load_generated_ideas(path) == []


def test_all_ideas_can_be_deleted_at_once(tmp_path: Path) -> None:
    saved_path = tmp_path / "saved-ideas.json"
    generated_path = tmp_path / "generated-ideas.json"
    save_idea({"id": "saved-1", "title": "A ideia salva"}, saved_path)
    replace_generated_ideas([{"id": "generated-1", "title": "A ideia gerada"}], generated_path)

    deleted_count = delete_all_ideas(saved_path, generated_path)

    assert deleted_count == 2
    assert load_saved_ideas(saved_path) == []
    assert load_generated_ideas(generated_path) == []
