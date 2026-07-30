import io
import json
import urllib.error
import urllib.request
from email.message import Message
from typing import Any, cast

import pytest

from app.config.settings import Settings
from app.generation import model_settings
from app.providers.llm.openai_compatible import (
    OpenAICompatibleLLMConfig,
    OpenAICompatibleLLMProvider,
)
from app.providers.llm.types import LLMRequest


class _JsonResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.headers: dict[str, str] = {}

    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _http_error(status: int, payload: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://provider.test/v1/chat/completions",
        code=status,
        msg="provider error",
        hdrs=Message(),
        fp=io.BytesIO(payload.encode("utf-8")),
    )


def _request_json_body(request: urllib.request.Request) -> dict[str, Any]:
    data = cast(bytes, request.data or b"{}")
    return cast(dict[str, Any], json.loads(data.decode("utf-8")))


def test_openai_compatible_provider_sends_chat_completion_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="groq",
            display_name="Groq",
            base_url="https://api.groq.com/openai/v1",
            api_key="groq-secret",
            api_key_env="GROQ_API_KEY",
        )
    )
    captured: dict[str, Any] = {}

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["body"] = _request_json_body(request)
        captured["timeout"] = kwargs.get("timeout")
        return _JsonResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    response = provider._send_request(
        LLMRequest(task="generate_story_ideas", prompt="{}", model="llama-3.3"),
        use_response_format=True,
    )

    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["authorization"] == "Bearer groq-secret"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["timeout"] == 300
    assert response["choices"][0]["message"]["content"] == '{"ok": true}'


def test_openai_compatible_provider_retries_without_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="ollama",
            display_name="Ollama",
            base_url="http://localhost:11434/v1",
            api_key="ollama",
            require_api_key=False,
        )
    )
    bodies: list[dict[str, Any]] = []

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        _ = kwargs
        bodies.append(_request_json_body(request))
        if len(bodies) == 1:
            raise _http_error(422, '{"error":"response_format unsupported"}')
        return _JsonResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    response = provider._send_request(
        LLMRequest(task="generate_story_ideas", prompt="{}", model="llama3.1:8b"),
        use_response_format=True,
    )

    assert "response_format" in bodies[0]
    assert "response_format" not in bodies[1]
    assert response["choices"][0]["message"]["content"] == '{"ok": true}'


def test_openai_compatible_provider_redacts_http_error_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="groq",
            display_name="Groq",
            base_url="https://api.groq.com/openai/v1",
            api_key="groq-secret",
            api_key_env="GROQ_API_KEY",
        )
    )

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        _ = request, kwargs
        raise _http_error(429, '{"error":"Authorization: Bearer groq-secret quota"}')

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(RuntimeError) as exc:
        provider._send_request(
            LLMRequest(task="generate_story_ideas", prompt="{}", model="llama-3.3"),
            use_response_format=True,
        )

    assert "Groq HTTP 429" in str(exc.value)
    assert "groq-secret" not in str(exc.value)
    assert "[REDACTED]" in str(exc.value)


def test_openai_compatible_provider_reports_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="groq",
            display_name="Groq",
            base_url="https://api.groq.com/openai/v1",
            api_key="groq-secret",
            api_key_env="GROQ_API_KEY",
        )
    )

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        _ = request, kwargs
        raise TimeoutError("slow")

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(RuntimeError, match="Groq timeout"):
        provider._send_request(
            LLMRequest(task="generate_story_ideas", prompt="{}", model="llama-3.3"),
            use_response_format=True,
        )


def test_llm_provider_for_name_supports_text_providers() -> None:
    settings = Settings(
        text_provider="ollama",
        groq_api_key="groq-secret",
        nvidia_nim_api_key="nv-secret",
    )

    ollama_provider = cast(Any, model_settings.llm_provider_for_name(settings, "ollama"))
    groq_provider = cast(Any, model_settings.llm_provider_for_name(settings, "groq"))
    nvidia_provider = cast(Any, model_settings.llm_provider_for_name(settings, "nvidia_nim"))

    assert ollama_provider.provider_name == "ollama"
    assert groq_provider.provider_name == "groq"
    assert nvidia_provider.provider_name == "nvidia_nim"


def test_llm_provider_for_name_requires_groq_api_key() -> None:
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        model_settings.llm_provider_for_name(Settings(groq_api_key=None), "groq")


def test_nvidia_nim_self_hosted_allows_missing_api_key() -> None:
    settings = Settings(
        nvidia_nim_api_key=None,
        nvidia_nim_base_url="http://localhost:8000/v1",
    )

    provider = cast(Any, model_settings.llm_provider_for_name(settings, "nvidia_nim"))

    assert provider.provider_name == "nvidia_nim"
