import asyncio
from pathlib import Path
from typing import NoReturn

import pytest

from app.config.settings import Settings
from app.providers.llm.types import LLMRequest, LLMResult
from app.storytelling import idea_lab
from app.storytelling.idea_lab import (
    build_idea_lab_prompt,
    delete_all_ideas,
    delete_generated_idea,
    delete_saved_idea,
    generate_freeform_ideas,
    load_generated_ideas,
    load_saved_ideas,
    replace_generated_ideas,
    save_idea,
)
from app.storytelling.story_idea_normalization import _normalize_generated_story_ideas


def test_idea_lab_prompt_guides_quality_and_output_contract() -> None:
    prompt = build_idea_lab_prompt(
        "historias sobre escolhas impossiveis",
        count=4,
        genre="Drama",
        duration_minutes=20,
        retry_guidance="campo obrigatorio vazio: conflict",
    )

    assert "gere exatamente 4 ideias" in prompt
    assert "Duracao obrigatoria" in prompt
    assert "20 minutos" in prompt
    assert "Genero obrigatorio" in prompt
    assert "Drama" in prompt
    assert "Nao numere os titulos" in prompt
    assert "somente JSON valido" in prompt
    assert '"ideas"' in prompt
    assert "duration_minutes igual a 20" in prompt
    assert "campo obrigatorio vazio: conflict" in prompt


def test_project_story_idea_normalization_accepts_one_valid_idea() -> None:
    ideas = _normalize_generated_story_ideas(
        {
            "ideas": [
                {
                    "title": "A ponte de vidro",
                    "genre": "Drama",
                    "primary_emotion": "Coragem",
                    "theme": "reconciliação pública",
                    "hook": "Uma engenheira precisa atravessar a ponte que jurou demolir.",
                    "premise": (
                        "Após um acidente antigo, ela volta à cidade para provar que a "
                        "estrutura ainda pode salvar pessoas."
                    ),
                    "protagonist": "Marta, uma engenheira de pontes",
                    "conflict": "Assinar o laudo reacende a culpa pelo acidente.",
                    "obstacles": ["moradores hostis", "provas incompletas"],
                    "stakes": "A cidade pode ficar isolada durante uma enchente.",
                    "twist": "O erro original não foi dela, mas ela encobriu o responsável.",
                    "climax": "Marta atravessa a ponte durante a evacuação.",
                    "payoff": "Ela escolhe verdade em vez de reputação.",
                    "resolution": "A ponte é reparada e recebe o nome das vítimas.",
                    "duration_minutes": 5,
                    "retention_potential": 78,
                    "cliche_risk": 22,
                    "production_complexity": 40,
                }
            ]
        },
        5,
    )

    assert len(ideas) == 1
    assert ideas[0]["title"] == "A ponte de vidro"


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
async def test_generate_freeform_ideas_supports_twenty_five_minutes_and_clamps_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(idea_lab, "get_settings", lambda: Settings(openrouter_api_key=None))
    ideas = await generate_freeform_ideas(count=99, target_duration_minutes=25)

    assert len(ideas) == 10
    assert {int(idea.get("duration_minutes", 0)) for idea in ideas} == {25}


@pytest.mark.asyncio
async def test_generate_freeform_ideas_reports_openrouter_failure(
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

    with pytest.raises(RuntimeError, match="Nao foi possivel gerar ideias"):
        await generate_freeform_ideas(count=3, genre="Suspense")


@pytest.mark.asyncio
async def test_generate_freeform_ideas_reports_openrouter_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowOpenRouterProvider:
        provider_name = "openrouter"

        async def generate_structured(self, request: LLMRequest) -> LLMResult:
            await asyncio.sleep(0.05)
            raise AssertionError("provider should time out first")

    monkeypatch.setattr(
        idea_lab,
        "get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test", openrouter_default_model="free-model"),
    )
    monkeypatch.setattr(idea_lab, "OpenRouterLLMProvider", SlowOpenRouterProvider)
    monkeypatch.setattr(idea_lab, "IDEA_PROVIDER_TIMEOUT_SECONDS", 0.001)

    with pytest.raises(RuntimeError, match="demorou mais"):
        await generate_freeform_ideas(count=3, genre="Drama")


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


@pytest.mark.asyncio
async def test_generate_freeform_ideas_keeps_partial_valid_openrouter_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PartialProvider:
        provider_name = "openrouter"

        async def generate_structured(self, request: LLMRequest) -> LLMResult:
            return LLMResult(
                content={
                    "ideas": [
                        {
                            "title": "O farol apagado",
                            "genre": "Drama",
                            "primary_emotion": "Esperança",
                            "theme": "luto e recomeço",
                            "hook": "Uma faroleira acende a luz para um barco que não existe.",
                            "premise": (
                                "Depois de perder o pai no mar, uma jovem mantém o farol ligado "
                                "até descobrir quem ainda depende daquela luz."
                            ),
                            "protagonist": "Lia, uma faroleira teimosa",
                            "conflict": "A cidade quer desligar o farol para sempre.",
                            "obstacles": ["tempestade", "pressão dos moradores"],
                            "stakes": "A memória do pai pode virar apenas ruína.",
                            "twist": "O barco era um pedido antigo de socorro registrado errado.",
                            "climax": "Lia sobe ao farol durante a maior tempestade do ano.",
                            "payoff": "Ela entende que manter a luz acesa também salva os vivos.",
                            "resolution": "O farol vira estação de resgate comunitária.",
                            "duration_minutes": 5,
                            "retention_potential": 80,
                            "cliche_risk": 20,
                            "production_complexity": 35,
                        }
                    ]
                },
                model=request.model,
                provider=self.provider_name,
            )

    monkeypatch.setattr(
        idea_lab,
        "get_settings",
        lambda: Settings(openrouter_api_key="sk-or-v1-test", openrouter_default_model="free-model"),
    )
    monkeypatch.setattr(idea_lab, "OpenRouterLLMProvider", PartialProvider)

    ideas = await generate_freeform_ideas(count=3, genre="Drama")

    assert len(ideas) == 1
    assert ideas[0]["title"] == "O farol apagado"


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


def test_saving_same_idea_content_does_not_duplicate_saved_list(tmp_path: Path) -> None:
    path = tmp_path / "saved-ideas.json"
    save_idea(
        {
            "id": "idea-1",
            "title": "A chave no jardim",
            "genre": "Suspense",
            "primary_emotion": "Curiosidade",
            "premise": "Uma chave muda de lugar a cada mentira.",
            "duration_minutes": 10,
        },
        path,
    )
    save_idea(
        {
            "id": "idea-2",
            "title": "A chave no jardim",
            "genre": "Suspense",
            "primary_emotion": "Curiosidade",
            "premise": "Uma chave muda de lugar a cada mentira.",
            "duration_minutes": 10,
        },
        path,
    )

    saved = load_saved_ideas(path)

    assert len(saved) == 1
    assert saved[0]["id"] == "idea-2"


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
