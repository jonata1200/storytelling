from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.generation import service as generation_service
from app.generation.prompt_compiler import compile_prompt
from app.generation.service import (
    DEFAULT_TEMPLATES,
    run_structured_generation,
    should_fallback_to_mock,
)
from app.providers.llm.types import LLMRequest


def test_compile_prompt_keeps_missing_variables_visible() -> None:
    prompt = compile_prompt("Tema: {theme}. Publico: {audience}.", {"theme": "perdao"})

    assert prompt == "Tema: perdao. Publico: {audience}."


def test_default_generation_templates_with_json_examples_compile() -> None:
    variables = {
        "target_duration_minutes": 5,
        "theme": "perdao",
        "audience": "publico geral",
        "primary_emotion": "esperanca",
        "idea_title": "A carta",
        "idea": {"title": "A carta"},
        "language": "pt-BR",
        "target_duration_seconds": 300,
        "story_bible": {"title": "A carta"},
        "script": "Roteiro atual",
        "instruction": "melhore o gancho",
        "project_context": {"project": "A carta"},
        "current_script": "Roteiro atual",
        "clip_min_seconds": 4,
        "clip_max_seconds": 15,
        "clip_target_seconds": 15,
        "expected_clip_count": 20,
        "clip_durations": "15s, 15s",
    }

    compiled = {
        task: compile_prompt(template, variables)
        for task, template in DEFAULT_TEMPLATES.items()
    }

    assert '"content":"ROTEIRO-BASE COMPLETO AQUI"' in compiled["generate_script"]
    assert "Seedance 2.0 Fast" in compiled["generate_script"]
    assert "entre 4s e 15s" in compiled["generate_scenes_and_shots"]
    assert "indicacao para video" in compiled["revise_script"]
    assert '"scenes"' in compiled["generate_scenes_and_shots"]
    assert '"ideas"' in compiled["generate_story_ideas"]


def test_generation_fallback_detects_openrouter_resource_exhaustion() -> None:
    error = RuntimeError(
        "OpenRouter retornou erro: Upstream error from Nvidia: "
        "ResourceExhausted: Worker local total request limit reached (32/32)"
    )

    assert should_fallback_to_mock(error) is True


def test_generation_fallback_detects_openrouter_malformed_model_response() -> None:
    error = RuntimeError("OpenRouter retornou conteudo que nao e JSON valido")

    assert should_fallback_to_mock(error) is True


def test_generation_fallback_ignores_schema_errors() -> None:
    error = RuntimeError("generate_script: empty field 'content'")

    assert should_fallback_to_mock(error) is False


@pytest.mark.asyncio
async def test_director_generation_can_fallback_on_any_openrouter_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        provider_name = "openrouter"

        async def generate_structured(self, request: LLMRequest):
            raise RuntimeError("OpenRouter retornou conteudo que nao e JSON valido")

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

    result, execution = await run_structured_generation(
        session,  # type: ignore[arg-type]
        FailingProvider(),
        uuid4(),
        "director_agent_chat",
        {"prompt": "Ajude no roteiro", "section": "script"},
        model="unstable-model",
        fallback_on_runtime_error=True,
    )

    assert result.provider == "mock"
    assert execution.provider == "mock"
    assert execution.model == "mock-llm"
    assert execution.parameters["fallback_from"] == "unstable-model"
    assert "nao e JSON valido" in execution.parameters["fallback_error"]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_structured_generation_keeps_schema_errors_without_chat_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        provider_name = "openrouter"

        async def generate_structured(self, request: LLMRequest):
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
