import json
import urllib.request
from typing import Any, cast

import pytest

from app.config.settings import Settings
from app.generation import model_settings
from app.providers.llm.ollama_cloud import OllamaCloudLLMProvider
from app.providers.llm.types import LLMRequest


class _JsonResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.headers: dict[str, str] = {"content-type": "application/json"}

    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _request_json_body(request: urllib.request.Request) -> dict[str, Any]:
    data = cast(bytes, request.data or b"{}")
    return cast(dict[str, Any], json.loads(data.decode("utf-8")))


@pytest.mark.asyncio
async def test_ollama_cloud_provider_sends_native_chat_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        text_provider="ollama_cloud",
        ollama_cloud_api_key="ollama-secret",
        ollama_cloud_base_url="https://ollama.com/api",
        ollama_cloud_default_model="mistral-large-3:675b-cloud",
    )
    monkeypatch.setattr("app.providers.llm.ollama_cloud.get_settings", lambda: settings)
    captured: dict[str, Any] = {}

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["body"] = _request_json_body(request)
        captured["timeout"] = kwargs.get("timeout")
        return _JsonResponse(
            {
                "model": "mistral-large-3:675b-cloud",
                "message": {"role": "assistant", "content": '{"ok": true}'},
                "done": True,
                "prompt_eval_count": 12,
                "eval_count": 4,
            }
        )

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = await OllamaCloudLLMProvider().generate_structured(
        LLMRequest(
            task="generate_story_ideas",
            prompt='Retorne {"ok": true}',
            model="mistral-large-3:675b-cloud",
            timeout_seconds=60,
        )
    )

    assert captured["url"] == "https://ollama.com/api/chat"
    assert captured["authorization"] == "Bearer ollama-secret"
    assert captured["body"]["stream"] is False
    assert "format" not in captured["body"]
    assert captured["timeout"] == 60
    assert result.provider == "ollama_cloud"
    assert result.model == "mistral-large-3:675b-cloud"
    assert result.content == {"ok": True}
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 4


@pytest.mark.asyncio
async def test_ollama_cloud_provider_accepts_content_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        text_provider="ollama_cloud",
        ollama_cloud_api_key="ollama-secret",
        ollama_cloud_base_url="https://ollama.com/api",
        ollama_cloud_default_model="mistral-large-3:675b-cloud",
    )
    monkeypatch.setattr("app.providers.llm.ollama_cloud.get_settings", lambda: settings)

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        return _JsonResponse(
            {
                "model": "mistral-large-3:675b-cloud",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": '{"ok": true}'}],
                },
                "done": True,
            }
        )

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = await OllamaCloudLLMProvider().generate_structured(
        LLMRequest(
            task="generate_script",
            prompt='Retorne {"ok": true}',
            model="mistral-large-3:675b-cloud",
            timeout_seconds=60,
        )
    )

    assert result.content == {"ok": True}


@pytest.mark.asyncio
async def test_ollama_cloud_provider_accepts_openai_compatible_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        text_provider="ollama_cloud",
        ollama_cloud_api_key="ollama-secret",
        ollama_cloud_base_url="https://ollama.com/api",
        ollama_cloud_default_model="mistral-large-3:675b-cloud",
    )
    monkeypatch.setattr("app.providers.llm.ollama_cloud.get_settings", lambda: settings)

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        return _JsonResponse(
            {
                "model": "mistral-large-3:675b-cloud",
                "message": {"role": "assistant", "content": ""},
                "choices": [{"message": {"content": '{"ok": true}'}}],
            }
        )

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = await OllamaCloudLLMProvider().generate_structured(
        LLMRequest(
            task="generate_script",
            prompt='Retorne {"ok": true}',
            model="mistral-large-3:675b-cloud",
            timeout_seconds=60,
        )
    )

    assert result.content == {"ok": True}


@pytest.mark.asyncio
async def test_ollama_cloud_provider_retries_empty_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        text_provider="ollama_cloud",
        ollama_cloud_api_key="ollama-secret",
        ollama_cloud_base_url="https://ollama.com/api",
        ollama_cloud_default_model="mistral-large-3:675b-cloud",
    )
    monkeypatch.setattr("app.providers.llm.ollama_cloud.get_settings", lambda: settings)
    monkeypatch.setattr(
        OllamaCloudLLMProvider,
        "_sleep_before_retry",
        lambda self, headers, attempt: None,
    )
    calls = 0

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _JsonResponse(
                {
                    "model": "mistral-large-3:675b-cloud",
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                }
            )
        return _JsonResponse(
            {
                "model": "mistral-large-3:675b-cloud",
                "message": {"role": "assistant", "content": '{"ok": true}'},
                "done": True,
            }
        )

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = await OllamaCloudLLMProvider().generate_structured(
        LLMRequest(
            task="generate_script",
            prompt='Retorne {"ok": true}',
            model="mistral-large-3:675b-cloud",
            timeout_seconds=60,
        )
    )

    assert calls == 2
    assert result.content == {"ok": True}


def test_llm_provider_for_name_supports_ollama_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        text_provider="ollama_cloud",
        ollama_cloud_api_key="ollama-secret",
    )
    monkeypatch.setattr("app.providers.llm.ollama_cloud.get_settings", lambda: settings)

    provider = cast(Any, model_settings.llm_provider_for_name(settings, "ollama_cloud"))

    assert provider.provider_name == "ollama_cloud"

