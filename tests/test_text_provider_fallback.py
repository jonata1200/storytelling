from types import SimpleNamespace
from typing import NoReturn
from uuid import uuid4

import pytest

import app.generation.model_settings as model_settings
import app.generation.service as generation_service
from app.config.settings import Settings
from app.generation.service import run_structured_generation
from app.providers.llm.types import LLMRequest, LLMResult


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flushed = True


async def _fake_template(session: object, task: str) -> SimpleNamespace:
    _ = session
    return SimpleNamespace(id=uuid4(), version=1, template_text="{prompt}", output_schema={})


@pytest.mark.asyncio
async def test_text_provider_fallback_records_final_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        provider_name = "groq"

        async def generate_structured(self, request: LLMRequest) -> NoReturn:
            raise RuntimeError("Groq HTTP 429: Authorization: Bearer groq-secret quota")

    class FallbackProvider:
        provider_name = "ollama"

        async def generate_structured(self, request: LLMRequest) -> LLMResult:
            return LLMResult(
                content={"ok": True},
                model=request.model,
                provider=self.provider_name,
            )

    settings = Settings(
        ai_provider="omniroute",
        text_provider="groq",
        text_provider_fallbacks="ollama",
        groq_api_key="groq-secret",
        groq_default_model="llama-3.3-70b-versatile",
        ollama_default_model="llama3.1:8b",
    )
    monkeypatch.setattr(generation_service, "get_settings", lambda: settings)
    monkeypatch.setattr(generation_service, "get_or_create_prompt_template", _fake_template)
    monkeypatch.setattr(
        model_settings,
        "llm_provider_for_name",
        lambda _settings, provider_name: FallbackProvider(),
    )

    session = _FakeSession()
    result, execution = await run_structured_generation(
        session,  # type: ignore[arg-type]
        FailingProvider(),
        uuid4(),
        "generate_story_ideas",
        {"prompt": "Ideia"},
        model="llama-3.3-70b-versatile",
        fallback_on_runtime_error=True,
    )

    assert result.content == {"ok": True}
    assert execution.provider == "ollama"
    assert execution.parameters["primary_provider"] == "groq"
    assert execution.parameters["final_provider"] == "ollama"
    assert "groq-secret" not in str(execution.parameters["fallback_attempts"])
    assert len(session.added) == 2
    assert session.flushed is True


@pytest.mark.asyncio
async def test_text_provider_fallback_does_not_mask_json_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        provider_name = "groq"

        async def generate_structured(self, request: LLMRequest) -> NoReturn:
            raise RuntimeError("Groq retornou conteudo que nao e JSON valido")

    settings = Settings(
        ai_provider="omniroute",
        text_provider="groq",
        text_provider_fallbacks="ollama",
        groq_api_key="groq-secret",
    )
    monkeypatch.setattr(generation_service, "get_settings", lambda: settings)
    monkeypatch.setattr(generation_service, "get_or_create_prompt_template", _fake_template)

    session = _FakeSession()
    with pytest.raises(RuntimeError, match="JSON valido"):
        await run_structured_generation(
            session,  # type: ignore[arg-type]
            FailingProvider(),
            uuid4(),
            "generate_story_ideas",
            {"prompt": "Ideia"},
            model="llama-3.3-70b-versatile",
            fallback_on_runtime_error=True,
        )

    assert session.added == []
    assert session.flushed is False
