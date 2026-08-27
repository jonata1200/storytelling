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


def _http_error(
    status: int,
    payload: str,
    headers: dict[str, str] | None = None,
) -> urllib.error.HTTPError:
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError(
        url="https://provider.test/v1/chat/completions",
        code=status,
        msg="provider error",
        hdrs=message,
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
            provider_name="test_provider",
            display_name="Provider Teste",
            base_url="https://provider.test/v1",
            api_key="nv-secret",
            api_key_env="TEST_PROVIDER_API_KEY",
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

    assert captured["url"] == "https://provider.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer nv-secret"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["timeout"] == 300
    assert response["choices"][0]["message"]["content"] == '{"ok": true}'


def test_openai_compatible_provider_retries_without_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="test_provider",
            display_name="Provider Teste",
            base_url="http://localhost:8000/v1",
            api_key=None,
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
        LLMRequest(task="generate_story_ideas", prompt="{}", model="z-ai/glm-5.2"),
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
            provider_name="test_provider",
            display_name="Provider Teste",
            base_url="https://provider.test/v1",
            api_key="nv-secret",
            api_key_env="TEST_PROVIDER_API_KEY",
        )
    )

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        _ = request, kwargs
        raise _http_error(429, '{"error":"Authorization: Bearer nv-secret quota"}')

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr("app.providers.llm.openai_compatible.time.sleep", lambda _delay: None)

    with pytest.raises(RuntimeError) as exc:
        provider._send_request(
            LLMRequest(task="generate_story_ideas", prompt="{}", model="llama-3.3"),
            use_response_format=True,
        )

    assert "Provider Teste HTTP 429" in str(exc.value)
    assert "nv-secret" not in str(exc.value)
    assert "[REDACTED]" in str(exc.value)


def test_openai_compatible_provider_retries_transient_resource_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="test_provider",
            display_name="Provider Teste",
            base_url="https://provider.test/v1",
            api_key="nv-secret",
            api_key_env="TEST_PROVIDER_API_KEY",
        )
    )
    sleeps: list[float] = []
    attempts = 0

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        nonlocal attempts
        _ = request, kwargs
        attempts += 1
        if attempts == 1:
            raise _http_error(
                503,
                (
                    '{"error":{"message":"ResourceExhausted: Worker local total '
                    'request limit reached"}}'
                ),
                {"Retry-After": "0.5"},
            )
        return _JsonResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.time.sleep",
        lambda delay: sleeps.append(delay),
    )

    response = provider._send_request(
        LLMRequest(task="generate_script", prompt="{}", model="test/model"),
        use_response_format=True,
    )

    assert attempts == 2
    assert sleeps == [0.5]
    assert response["choices"][0]["message"]["content"] == '{"ok": true}'


def test_openai_compatible_provider_explains_resource_exhausted_after_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="test_provider",
            display_name="Provider Teste",
            base_url="https://provider.test/v1",
            api_key="nv-secret",
            api_key_env="TEST_PROVIDER_API_KEY",
        )
    )

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        _ = request, kwargs
        raise _http_error(
            503,
            (
                '{"error":{"message":"ResourceExhausted: Worker local total '
                'request limit reached (33/16)"}}'
            ),
        )

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr("app.providers.llm.openai_compatible.time.sleep", lambda _delay: None)

    with pytest.raises(RuntimeError) as exc:
        provider._send_request(
            LLMRequest(task="generate_script", prompt="{}", model="test/model"),
            use_response_format=True,
        )

    assert "limite temporario de capacidade" in str(exc.value)
    assert "modelo menor/mais estavel" in str(exc.value)
    assert "Modelo: test/model" in str(exc.value)


def test_openai_compatible_provider_explains_model_not_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="test_provider",
            display_name="Provider Teste",
            base_url="https://provider.test/v1",
            api_key="nv-secret",
            api_key_env="TEST_PROVIDER_API_KEY",
        )
    )

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        _ = request, kwargs
        raise _http_error(
            404,
            (
                '{"status":404,"title":"Not Found","detail":"Function '
                "'abc': Not found for account 'account-id'\"}"
            ),
        )

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(RuntimeError) as exc:
        provider._send_request(
            LLMRequest(
                task="generate_script",
                prompt="{}",
                model="deepseek-ai/deepseek-v4-flash",
            ),
            use_response_format=True,
        )

    message = str(exc.value)
    assert "modelo selecionado nao esta disponivel" in message
    assert "Modelo: deepseek-ai/deepseek-v4-flash" in message


def test_openai_compatible_provider_retries_runtime_timeout_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="test_provider",
            display_name="Provider Teste",
            base_url="https://provider.test/v1",
            api_key="nv-secret",
            api_key_env="TEST_PROVIDER_API_KEY",
        )
    )
    sleeps: list[float] = []
    attempts = 0

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        nonlocal attempts
        _ = request, kwargs
        attempts += 1
        if attempts == 1:
            raise TimeoutError("slow")
        return _JsonResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.time.sleep",
        lambda delay: sleeps.append(delay),
    )

    response = provider._send_request(
        LLMRequest(task="generate_script", prompt="{}", model="test/model"),
        use_response_format=True,
    )

    assert attempts == 2
    assert sleeps == [4.0]
    assert response["choices"][0]["message"]["content"] == '{"ok": true}'


def test_openai_compatible_provider_reports_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="test_provider",
            display_name="Provider Teste",
            base_url="https://provider.test/v1",
            api_key="nv-secret",
            api_key_env="TEST_PROVIDER_API_KEY",
        )
    )

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        _ = request, kwargs
        raise TimeoutError("slow")

    monkeypatch.setattr(
        "app.providers.llm.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr("app.providers.llm.openai_compatible.time.sleep", lambda delay: None)

    with pytest.raises(RuntimeError, match="Provider Teste timeout"):
        provider._send_request(
            LLMRequest(task="generate_story_ideas", prompt="{}", model="llama-3.3"),
            use_response_format=True,
        )


def test_openai_compatible_recovers_plain_text_for_director_chat() -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="test_provider",
            display_name="Provider Teste",
            base_url="https://provider.test/v1",
            api_key=None,
            require_api_key=False,
        )
    )

    content, strategy = provider._parse_json_content(
        "Resposta livre do diretor sem json.",
        task="director_agent_chat",
    )

    assert strategy == "plain_text_message"
    assert content == {"message": "Resposta livre do diretor sem json."}


def test_openai_compatible_recovers_non_object_json_for_director_chat() -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="test_provider",
            display_name="Provider Teste",
            base_url="https://provider.test/v1",
            api_key=None,
            require_api_key=False,
        )
    )

    content, strategy = provider._parse_json_content(
        '"apenas uma string json"',
        task="director_agent_chat",
    )

    assert strategy == "plain_text_message"
    assert content == {"message": '"apenas uma string json"'}


def test_openai_compatible_still_rejects_non_json_for_other_tasks() -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatibleLLMConfig(
            provider_name="test_provider",
            display_name="Provider Teste",
            base_url="https://provider.test/v1",
            api_key=None,
            require_api_key=False,
        )
    )

    with pytest.raises(RuntimeError, match="nao e JSON valido"):
        provider._parse_json_content("texto solto sem json", task="generate_story_ideas")


def test_llm_provider_for_name_supports_text_providers() -> None:
    settings = Settings(meta_api_key="meta-secret")

    meta_provider = cast(Any, model_settings.llm_provider_for_name(settings, "meta"))

    assert meta_provider.provider_name == "meta"


def test_llm_provider_for_name_rejects_removed_text_providers() -> None:
    settings = Settings(meta_api_key="meta-secret")

    with pytest.raises(ValueError, match="Provider de texto não suportado"):
        model_settings.llm_provider_for_name(settings, "groq")
