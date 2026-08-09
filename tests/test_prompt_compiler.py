import asyncio
from types import SimpleNamespace
from typing import NoReturn
from uuid import uuid4

import pytest

from app.generation import service as generation_service
from app.generation.prompt_compiler import compile_prompt
from app.generation.service import (
    DEFAULT_TEMPLATES,
    run_structured_generation,
    should_fallback_to_mock,
)
from app.providers.llm.types import LLMRequest, LLMResult


def test_compile_prompt_keeps_missing_variables_visible() -> None:
    prompt = compile_prompt("Tema: {theme}. Publico: {audience}.", {"theme": "perdao"})

    assert prompt == "Tema: perdao. Publico: {audience}."


def test_default_generation_templates_with_json_examples_compile() -> None:
    variables = {
        "target_duration_minutes": 5,
        "theme": "perdao",
        "genre": "drama",
        "audience": "público geral",
        "primary_emotion": "esperanca",
        "diversity_memory": "nenhuma ideia anterior",
        "idea_title": "A carta",
        "idea": {"title": "A carta"},
        "language": "pt-BR",
        "target_duration_seconds": 300,
        "narrative_contract": {"title": "A carta"},
        "script": "Roteiro atual",
        "instruction": "melhore o gancho",
        "project_context": {"project": "A carta"},
        "current_script": "Roteiro atual",
        "clip_min_seconds": 4,
        "clip_max_seconds": 8,
        "clip_target_seconds": 8,
        "expected_clip_count": 38,
        "expected_scene_count": 5,
        "clip_durations": "8s, 8s",
        "retry_guidance": "",
    }

    compiled = {
        task: compile_prompt(template, variables)
        for task, template in DEFAULT_TEMPLATES.items()
    }

    assert '"content":"ROTEIRO CINEMATOGRAFICO COMPLETO AQUI"' in compiled["generate_script"]
    assert '"production_plan"' not in compiled["generate_script"]
    assert "Escreva somente o roteiro cinematográfico" in compiled["generate_script"]
    assert "FADE IN:" in compiled["generate_script"]
    assert "slugline" in compiled["generate_script"]
    assert "Não use listas técnicas" in compiled["generate_script"]
    assert "exatamente 5 cenas" in compiled["generate_script"]
    assert "roteirista cinematográfico senior" in compiled["generate_script"]
    assert "protagonista ativo" in compiled["generate_script"]
    assert "Nenhuma cena deve parecer preenchimento" in compiled["generate_script"]
    assert "Nunca use nomes de locais" in compiled["generate_script"]
    assert "alta retenção emocional" in compiled["generate_script"]
    assert "Responda somente JSON válido" in compiled["generate_script"]
    assert "exatamente 4s, 6s ou 8s" in compiled["generate_scenes_and_shots"]
    assert "ROTEIRO CINEMATOGRAFICO REVISADO COMPLETO AQUI" in compiled["revise_script"]
    assert "nunca o nome de um local" in compiled["revise_script"]
    assert '"scenes"' in compiled["generate_scenes_and_shots"]
    assert '"ideas"' in compiled["generate_story_ideas"]
    assert "Gênero preferido: drama" in compiled["generate_story_ideas"]
    assert '"payoff"' in compiled["generate_story_ideas"]
    assert "radicalmente diferentes entre si" in compiled["generate_story_ideas"]
    assert "nenhuma ideia anterior" in compiled["generate_story_ideas"]
    assert "contrato narrativo" in compiled["generate_script"]


def test_text_generation_timeout_budget_stays_bounded_for_ui_flows() -> None:
    assert generation_service.LLM_PROVIDER_TIMEOUT_SECONDS <= 180
    assert generation_service.TASK_TIMEOUT_SECONDS["generate_story_ideas"] <= 75
    for task in (
        "generate_script",
        "generate_scenes_and_shots",
        "generate_visual_bible",
        "generate_storyboard_prompts",
        "revise_script",
    ):
        assert generation_service.TASK_TIMEOUT_SECONDS[task] <= 180


def test_generation_fallback_detects_provider_resource_exhaustion() -> None:
    error = RuntimeError(
        "Provider retornou erro: upstream service: "
        "ResourceExhausted: Worker local total request limit reached (32/32)"
    )

    assert should_fallback_to_mock(error) is True


def test_generation_fallback_detects_provider_malformed_model_response() -> None:
    error = RuntimeError("Provider retornou conteúdo que não é JSON válido")

    assert should_fallback_to_mock(error) is True


def test_generation_fallback_ignores_schema_errors() -> None:
    error = RuntimeError("generate_script: empty field 'content'")

    assert should_fallback_to_mock(error) is False


def test_creative_narrative_tasks_do_not_allow_runtime_mock_fallback() -> None:
    assert generation_service.allow_runtime_mock_fallback("generate_story_ideas", True) is False
    assert generation_service.allow_runtime_mock_fallback("generate_script", True) is False
    assert generation_service.allow_runtime_mock_fallback("director_agent_chat", True) is False


@pytest.mark.asyncio
async def test_director_generation_reports_provider_runtime_error_without_mock_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        provider_name = "Provider"

        async def generate_structured(self, request: LLMRequest) -> NoReturn:
            raise RuntimeError("Provider retornou conteúdo que não é JSON válido")

    class FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.flushed = False

        def add(self, item: object) -> None:
            self.added.append(item)

        async def flush(self) -> None:
            self.flushed = True

    async def fake_template(session: object, task: str) -> SimpleNamespace:
        assert task == "director_agent_chat"
        return SimpleNamespace(id=uuid4(), version=1, template_text="{prompt}", output_schema={})

    session = FakeSession()
    monkeypatch.setattr(generation_service, "get_or_create_prompt_template", fake_template)

    with pytest.raises(RuntimeError, match="não é JSON válido"):
        await run_structured_generation(
            session,  # type: ignore[arg-type]
            FailingProvider(),
            uuid4(),
            "director_agent_chat",
            {"prompt": "Ajude no roteiro", "section": "script"},
            model="unstable-model",
            fallback_on_runtime_error=True,
        )

    assert session.flushed is False


@pytest.mark.asyncio
async def test_structured_generation_reports_timeout_without_mock_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowProvider:
        provider_name = "Provider"

        async def generate_structured(self, request: LLMRequest) -> object:
            await asyncio.sleep(0.05)
            raise AssertionError("provider should time out first")

    class FakeSession:
        flushed = False

        def add(self, item: object) -> None:
            self.item = item

        async def flush(self) -> None:
            self.flushed = True

    async def fake_template(session: object, task: str) -> SimpleNamespace:
        return SimpleNamespace(id=uuid4(), version=1, template_text="{prompt}", output_schema={})

    monkeypatch.setattr(generation_service, "get_or_create_prompt_template", fake_template)
    monkeypatch.setattr(generation_service, "LLM_PROVIDER_TIMEOUT_SECONDS", 0.001)

    session = FakeSession()
    with pytest.raises(RuntimeError, match="Provider demorou mais"):
        await run_structured_generation(
            session,  # type: ignore[arg-type]
            SlowProvider(),  # type: ignore[arg-type]
            uuid4(),
            "director_agent_chat",
            {"prompt": "Ajude", "section": "script"},
            model="slow-model",
            fallback_on_runtime_error=True,
        )

    assert session.flushed is False


@pytest.mark.asyncio
async def test_structured_generation_records_recovered_raw_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecoveringProvider:
        provider_name = "Provider"

        async def generate_structured(self, request: LLMRequest) -> LLMResult:
            return LLMResult(
                content={"content": "FADE IN:\n\nCENA 01\nINT. CASA - DIA\n\nA porta abre."},
                model=request.model,
                provider="ollama_cloud",
                raw_content="FADE IN:\n\nCENA 01\nINT. CASA - DIA\n\nA porta abre.",
                recovery_strategy="screenplay_text",
            )

    class FakeSession:
        def __init__(self) -> None:
            self.item: object | None = None
            self.flushed = False

        def add(self, item: object) -> None:
            self.item = item

        async def flush(self) -> None:
            self.flushed = True

    async def fake_template(session: object, task: str) -> SimpleNamespace:
        return SimpleNamespace(id=uuid4(), version=1, template_text="{prompt}", output_schema={})

    monkeypatch.setattr(generation_service, "get_or_create_prompt_template", fake_template)

    session = FakeSession()
    _result, execution = await run_structured_generation(
        session,  # type: ignore[arg-type]
        RecoveringProvider(),
        uuid4(),
        "generate_script",
        {"prompt": "Gere roteiro"},
        model="script-model",
    )

    assert session.flushed is True
    assert execution.parameters["recovery_strategy"] == "screenplay_text"
    assert "FADE IN" in execution.parameters["raw_response_preview"]


@pytest.mark.asyncio
async def test_creative_structured_generation_reports_timeout_without_mock_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowProvider:
        provider_name = "Provider"

        async def generate_structured(self, request: LLMRequest) -> object:
            await asyncio.sleep(0.05)
            raise AssertionError("provider should time out first")

    class FakeSession:
        def add(self, item: object) -> None:
            raise AssertionError("PromptExecution should not be created")

        async def flush(self) -> None:
            raise AssertionError("flush should not be called")

    async def fake_template(session: object, task: str) -> SimpleNamespace:
        return SimpleNamespace(id=uuid4(), version=1, template_text="{prompt}", output_schema={})

    monkeypatch.setattr(generation_service, "get_or_create_prompt_template", fake_template)
    monkeypatch.setattr(generation_service, "LLM_PROVIDER_TIMEOUT_SECONDS", 0.001)

    with pytest.raises(RuntimeError, match="Provider demorou mais"):
        await run_structured_generation(
            FakeSession(),  # type: ignore[arg-type]
            SlowProvider(),  # type: ignore[arg-type]
            uuid4(),
            "generate_script",
            {"prompt": "Gere roteiro"},
            model="slow-model",
            fallback_on_runtime_error=True,
        )


@pytest.mark.asyncio
async def test_structured_generation_keeps_schema_errors_without_chat_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        provider_name = "Provider"

        async def generate_structured(self, request: LLMRequest) -> NoReturn:
            raise RuntimeError("generate_script: empty field 'content'")

    class FakeSession:
        def add(self, item: object) -> None:
            raise AssertionError("PromptExecution should not be created")

        async def flush(self) -> None:
            raise AssertionError("flush should not be called")

    async def fake_template(session: object, task: str) -> SimpleNamespace:
        return SimpleNamespace(id=uuid4(), version=1, template_text="{prompt}", output_schema={})

    monkeypatch.setattr(generation_service, "get_or_create_prompt_template", fake_template)

    with pytest.raises(RuntimeError, match="empty field"):
        await run_structured_generation(
            FakeSession(),  # type: ignore[arg-type]
            FailingProvider(),
            uuid4(),
            "generate_script",
            {"prompt": "Gere roteiro"},
            model="unstable-model",
        )

