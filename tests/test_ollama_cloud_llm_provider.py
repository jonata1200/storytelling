import json
from typing import Any

import pytest

import app.providers.llm.ollama_cloud as ollama_module
from app.config.settings import Settings
from app.providers.llm.ollama_cloud import OllamaCloudLLMProvider
from app.providers.llm.types import LLMRequest


class Response:
    headers: dict[str, str] = {"content-type": "application/json"}

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


async def test_ollama_cloud_uses_native_chat_api_and_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        ollama_cloud_api_key="fake-ollama-secret",
        ollama_cloud_base_url="https://ollama.com/api",
    )
    monkeypatch.setattr(ollama_module, "get_settings", lambda: settings)
    captured: dict[str, Any] = {}

    def urlopen(request: Any, timeout: float) -> Response:
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response(
            {
                "model": "gpt-oss:120b",
                "message": {"role": "assistant", "content": '{"title":"ok"}'},
                "prompt_eval_count": 10,
                "eval_count": 4,
            }
        )

    monkeypatch.setattr(ollama_module.urllib.request, "urlopen", urlopen)
    result = await OllamaCloudLLMProvider().generate_structured(
        LLMRequest(
            task="generate_story_ideas",
            prompt="Create one idea",
            model="gpt-oss:120b",
            output_schema={"type": "object", "properties": {"title": {"type": "string"}}},
        )
    )
    assert captured["url"] == "https://ollama.com/api/chat"
    assert captured["authorization"] == "Bearer fake-ollama-secret"
    assert captured["body"]["stream"] is False
    assert captured["body"]["format"]["type"] == "object"
    assert result.content == {"title": "ok"}
    assert result.provider == "ollama_cloud"
    assert result.prompt_tokens == 10


async def test_ollama_cloud_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, ollama_cloud_api_key=None)
    monkeypatch.setattr(ollama_module, "get_settings", lambda: settings)
    with pytest.raises(ValueError, match="OLLAMA_API_KEY"):
        await OllamaCloudLLMProvider().generate_structured(
            LLMRequest(task="test", prompt="test", model="gpt-oss:120b")
        )


async def test_ollama_cloud_parses_markdown_fenced_json(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        ollama_cloud_api_key="fake-ollama-secret",
        ollama_cloud_base_url="https://ollama.com/api",
    )
    monkeypatch.setattr(ollama_module, "get_settings", lambda: settings)

    def urlopen(request: Any, timeout: float) -> Response:
        return Response(
            {
                "model": "glm-5.3-flash:cloud",
                "message": {
                    "role": "assistant",
                    "content": '```json\n{"title":"ok","ideas":[]}\n```',
                },
                "prompt_eval_count": 10,
                "eval_count": 4,
            }
        )

    monkeypatch.setattr(ollama_module.urllib.request, "urlopen", urlopen)
    result = await OllamaCloudLLMProvider().generate_structured(
        LLMRequest(
            task="generate_story_ideas",
            prompt="Create one idea",
            model="glm-5.3-flash:cloud",
        )
    )
    assert result.content == {"title": "ok", "ideas": []}


async def test_ollama_cloud_parses_json_with_surrounding_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        ollama_cloud_api_key="fake-ollama-secret",
        ollama_cloud_base_url="https://ollama.com/api",
    )
    monkeypatch.setattr(ollama_module, "get_settings", lambda: settings)

    def urlopen(request: Any, timeout: float) -> Response:
        return Response(
            {
                "model": "minimax-m3:cloud",
                "message": {
                    "role": "assistant",
                    "content": 'Aqui está o resultado:\n{"title":"ok"}\nEspero que ajude.',
                },
                "prompt_eval_count": 10,
                "eval_count": 4,
            }
        )

    monkeypatch.setattr(ollama_module.urllib.request, "urlopen", urlopen)
    result = await OllamaCloudLLMProvider().generate_structured(
        LLMRequest(task="generate_story_ideas", prompt="Create one idea", model="minimax-m3:cloud")
    )
    assert result.content == {"title": "ok"}
