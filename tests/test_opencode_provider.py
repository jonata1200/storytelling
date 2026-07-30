import json
import urllib.request
from typing import Any, cast
from uuid import uuid4

import pytest

from app.config.settings import Settings
from app.generation import model_settings
from app.providers.llm.opencode import OpenCodeLLMProvider
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


def _request_json_body(request: urllib.request.Request) -> dict[str, Any]:
    data = cast(bytes, request.data or b"{}")
    return cast(dict[str, Any], json.loads(data.decode("utf-8")))


def test_opencode_llm_provider_uses_gateway_fallback_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenCodeLLMProvider()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.providers.llm.opencode.get_settings",
        lambda: Settings(
            ai_provider="omniroute",
            text_provider="opencode",
            omniroute_api_key="omni-secret",
            omniroute_base_url="https://omnirouters.com/v1",
            opencode_base_url="",
            opencode_default_model="oc/deepseek-v4-flash-free",
        ),
    )

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["body"] = _request_json_body(request)
        captured["timeout"] = kwargs.get("timeout")
        return _JsonResponse(
            {
                "model": "oc/deepseek-v4-flash-free",
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "cost": "0"},
            }
        )

    monkeypatch.setattr("app.providers.llm.opencode.urllib.request.urlopen", fake_urlopen)

    response = provider._send_request(
        LLMRequest(
            task="generate_story_ideas",
            prompt="{}",
            model="oc/deepseek-v4-flash-free",
        ),
        use_response_format=True,
    )

    assert captured["url"] == "https://omnirouters.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer omni-secret"
    assert captured["body"]["model"] == "oc/deepseek-v4-flash-free"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["timeout"] == 300
    assert response["choices"][0]["message"]["content"] == '{"ok": true}'


@pytest.mark.asyncio
async def test_llm_provider_for_task_uses_opencode_text_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_project_setting(*args: object, **kwargs: object) -> Any:
        return None

    monkeypatch.setattr(model_settings, "get_model_setting", no_project_setting)
    monkeypatch.setattr(
        model_settings,
        "get_settings",
        lambda: Settings(
            ai_provider="omniroute",
            text_provider="opencode",
            omniroute_api_key="omni-secret",
            opencode_default_model="oc/deepseek-v4-flash-free",
        ),
    )

    provider, model = await model_settings.llm_provider_for_task(
        object(),  # type: ignore[arg-type]
        uuid4(),
        "generate_story_ideas",
    )

    assert getattr(provider, "provider_name", None) == "opencode"
    assert model == "oc/deepseek-v4-flash-free"
