import io
import json
import urllib.error
from email.message import Message
from typing import Any

import pytest

from app.config.settings import Settings
from app.generation.model_settings import configured_text_llm_provider
from app.observability.middleware import correlation_id_var
from app.providers.llm.meta import MetaLLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleResponseFormatError
from app.providers.llm.types import LLMRequest


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.headers = {"content-type": "application/json"}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def _settings(**changes: Any) -> Settings:
    values: dict[str, Any] = {
        "text_provider": "meta",
        "meta_integration_mode": "api",
        "meta_api_key": "meta-secret",
        "meta_base_url": "https://models.meta.example/v1",
        "meta_default_model": "muse-spark-1.2",
    }
    values.update(changes)
    return Settings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_meta_provider_sends_structured_request_and_maps_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr("app.providers.llm.meta.get_settings", lambda: settings)
    captured: dict[str, Any] = {}
    provider = MetaLLMProvider()

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response(
            {
                "model": "muse-spark-1.2",
                "choices": [{"message": {"content": '{"ideas": []}'}}],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 4,
                    "cost": "0.000321",
                },
            }
        )

    monkeypatch.setattr(provider, "_urlopen", fake_urlopen)
    token = correlation_id_var.set("meta-test-correlation")
    try:
        result = await provider.generate_structured(
            LLMRequest(
                task="generate_story_ideas",
                prompt="Crie ideias em português brasileiro",
                model="muse-spark-1.2",
                timeout_seconds=45,
                output_schema={
                    "type": "object",
                    "properties": {"ideas": {"type": "array"}},
                    "required": ["ideas"],
                },
            )
        )
    finally:
        correlation_id_var.reset(token)

    assert captured["url"] == "https://models.meta.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer meta-secret"
    assert captured["headers"]["X-correlation-id"] == "meta-test-correlation"
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert captured["body"]["response_format"]["json_schema"]["strict"] is True
    assert captured["timeout"] == 45
    assert result.provider == "meta"
    assert result.content == {"ideas": []}
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 4
    assert result.estimated_cost == "0.000321"
    assert "meta-secret" not in repr(settings)


@pytest.mark.parametrize("status", [400, 401, 403])
@pytest.mark.asyncio
async def test_meta_provider_does_not_retry_non_transient_errors(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    settings = _settings()
    monkeypatch.setattr("app.providers.llm.meta.get_settings", lambda: settings)
    provider = MetaLLMProvider()
    calls = 0

    def fail_auth(_request: Any, _timeout: float) -> Any:
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            "https://models.meta.example/v1/chat/completions",
            status,
            "auth",
            Message(),
            io.BytesIO(b'{"error":"invalid api key"}'),
        )

    monkeypatch.setattr(provider, "_urlopen", fail_auth)
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        await provider.generate_structured(
            LLMRequest(task="generate_script", prompt="roteiro", model="muse-spark-1.2")
        )
    assert calls == 1


@pytest.mark.parametrize("status", [429, 500, 503])
@pytest.mark.asyncio
async def test_meta_provider_retries_only_transient_http_errors(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    settings = _settings()
    monkeypatch.setattr("app.providers.llm.meta.get_settings", lambda: settings)
    provider = MetaLLMProvider()
    calls = 0

    def transient_then_success(_request: Any, _timeout: float) -> _Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                "https://models.meta.example/v1/chat/completions",
                status,
                "transient",
                Message(),
                io.BytesIO(b'{"error":"temporarily unavailable"}'),
            )
        return _Response({"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(provider, "_urlopen", transient_then_success)
    monkeypatch.setattr(provider, "_sleep_before_retry", lambda *_args: None)
    result = await provider.generate_structured(
        LLMRequest(task="generate_script", prompt="roteiro", model="muse-spark-1.2")
    )
    assert calls == 2
    assert result.content == {"ok": True}


@pytest.mark.asyncio
async def test_meta_provider_reports_timeout_and_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr("app.providers.llm.meta.get_settings", lambda: settings)
    provider = MetaLLMProvider()
    monkeypatch.setattr(provider, "_sleep_before_retry", lambda *_args: None)
    monkeypatch.setattr(
        provider,
        "_urlopen",
        lambda *_args: (_ for _ in ()).throw(TimeoutError()),
    )
    with pytest.raises(RuntimeError, match="timeout"):
        await provider.generate_structured(
            LLMRequest(task="generate_script", prompt="roteiro", model="muse-spark-1.2")
        )

    monkeypatch.setattr(
        provider,
        "_urlopen",
        lambda *_args: _Response(
            {"choices": [{"message": {"content": "isto não é json"}}]}
        ),
    )
    with pytest.raises(OpenAICompatibleResponseFormatError, match="JSON valido"):
        await provider.generate_structured(
            LLMRequest(task="generate_story_ideas", prompt="ideias", model="muse-spark-1.2")
        )


def test_configured_meta_provider_and_required_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr("app.providers.llm.meta.get_settings", lambda: settings)
    provider, model, name = configured_text_llm_provider(settings)
    assert isinstance(provider, MetaLLMProvider)
    assert model == "muse-spark-1.2"
    assert name == "meta"

    missing_url = _settings(meta_base_url="")
    monkeypatch.setattr("app.providers.llm.meta.get_settings", lambda: missing_url)
    with pytest.raises(ValueError, match="META_BASE_URL"):
        MetaLLMProvider()._provider_config()
