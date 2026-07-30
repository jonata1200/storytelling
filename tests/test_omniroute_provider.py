import base64
import io
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from app.config.settings import Settings
from app.generation import model_settings
from app.providers.image.omniroute import OmniRouteImageProvider
from app.providers.image.types import ImageGenerationRequest
from app.providers.llm.omniroute import OmniRouteLLMProvider
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


class _BytesResponse:
    def __init__(self, payload: bytes, content_type: str) -> None:
        self.payload = payload
        self.headers = {"content-type": content_type}

    def __enter__(self) -> "_BytesResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def _http_error(status: int, payload: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://omnirouters.com/v1/test",
        code=status,
        msg="bad request",
        hdrs=Message(),
        fp=io.BytesIO(payload.encode("utf-8")),
    )


def _request_json_body(request: urllib.request.Request) -> dict[str, Any]:
    data = cast(bytes, request.data or b"{}")
    return cast(dict[str, Any], json.loads(data.decode("utf-8")))


def test_omniroute_llm_provider_sends_expected_request_and_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OmniRouteLLMProvider()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.providers.llm.omniroute.get_settings",
        lambda: Settings(
            ai_provider="omniroute",
            omniroute_api_key="omni-secret",
            omniroute_base_url="https://omnirouters.com/v1",
        ),
    )

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["content_type"] = request.get_header("Content-type")
        captured["body"] = _request_json_body(request)
        captured["timeout"] = kwargs.get("timeout")
        return _JsonResponse(
            {
                "model": "provider/text-model",
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "cost": "0.01"},
            }
        )

    monkeypatch.setattr("app.providers.llm.omniroute.urllib.request.urlopen", fake_urlopen)

    result = provider._send_request(
        LLMRequest(task="generate_story_ideas", prompt="{}", model="provider/text-model"),
        use_response_format=True,
    )

    assert captured["url"] == "https://omnirouters.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer omni-secret"
    assert captured["content_type"] == "application/json"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["timeout"] == 300
    assert result["choices"][0]["message"]["content"] == '{"ok": true}'


def test_omniroute_llm_provider_retries_without_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OmniRouteLLMProvider()
    posted_bodies: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "app.providers.llm.omniroute.get_settings",
        lambda: Settings(omniroute_api_key="omni-secret"),
    )

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        _ = kwargs
        body = _request_json_body(request)
        posted_bodies.append(body)
        if len(posted_bodies) == 1:
            raise _http_error(400, '{"error":"response_format unsupported"}')
        return _JsonResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr("app.providers.llm.omniroute.urllib.request.urlopen", fake_urlopen)

    response = provider._send_request(
        LLMRequest(task="generate_story_ideas", prompt="{}", model="provider/text-model"),
        use_response_format=True,
    )

    assert "response_format" in posted_bodies[0]
    assert "response_format" not in posted_bodies[1]
    assert response["choices"][0]["message"]["content"] == '{"ok": true}'


def test_omniroute_llm_provider_accepts_event_stream_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OmniRouteLLMProvider()

    monkeypatch.setattr(
        "app.providers.llm.omniroute.get_settings",
        lambda: Settings(
            omniroute_api_key="omni-secret",
            omniroute_base_url="http://localhost:20128/v1",
        ),
    )

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _BytesResponse:
        _ = request, kwargs
        return _BytesResponse(
            (
                b'data: {"model":"deepseek-v4-flash","choices":[{"delta":{"content":"{\\""}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":"\\": true}"}}]}\n\n'
                b"data: [DONE]\n\n"
            ),
            "text/event-stream",
        )

    monkeypatch.setattr("app.providers.llm.omniroute.urllib.request.urlopen", fake_urlopen)

    response = provider._send_request(
        LLMRequest(task="generate_story_ideas", prompt="{}", model="ds-web/deepseek-v4-flash"),
        use_response_format=True,
    )

    assert response["model"] == "deepseek-v4-flash"
    assert response["choices"][0]["message"]["content"] == '{"ok": true}'


def test_omniroute_llm_provider_retries_empty_stream_without_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OmniRouteLLMProvider()
    posted_bodies: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "app.providers.llm.omniroute.get_settings",
        lambda: Settings(
            omniroute_api_key="omni-secret",
            omniroute_base_url="http://localhost:20128/v1",
        ),
    )

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _BytesResponse:
        _ = kwargs
        posted_bodies.append(_request_json_body(request))
        if len(posted_bodies) == 1:
            return _BytesResponse(b"data: [DONE]\n\n", "text/event-stream")
        return _BytesResponse(
            b'{"choices":[{"message":{"content":"{\\"ok\\": true}"}}]}',
            "application/json",
        )

    monkeypatch.setattr("app.providers.llm.omniroute.urllib.request.urlopen", fake_urlopen)

    response = provider._send_request(
        LLMRequest(task="generate_story_ideas", prompt="{}", model="ds-web/deepseek-v4-flash"),
        use_response_format=True,
    )

    assert posted_bodies[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in posted_bodies[1]
    assert response["choices"][0]["message"]["content"] == '{"ok": true}'


def test_omniroute_llm_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OmniRouteLLMProvider()
    monkeypatch.setattr(
        "app.providers.llm.omniroute.get_settings",
        lambda: Settings(omniroute_api_key=None),
    )

    with pytest.raises(ValueError, match="OMNIROUTE_API_KEY"):
        provider._send_request(
            LLMRequest(task="generate_story_ideas", prompt="{}", model="provider/text-model"),
            use_response_format=True,
        )


def test_omniroute_llm_provider_parses_json_content() -> None:
    provider = OmniRouteLLMProvider()

    assert provider._parse_json_content('```json\n{"ideas": []}\n```') == ({"ideas": []}, None)


def test_omniroute_llm_provider_recovers_embedded_json_content() -> None:
    provider = OmniRouteLLMProvider()

    assert provider._parse_json_content('Claro.\n{"title":"Teste","content":"ok"}\nFim.') == (
        {"title": "Teste", "content": "ok"},
        "embedded_json",
    )


def test_omniroute_llm_provider_recovers_screenplay_text_for_script() -> None:
    provider = OmniRouteLLMProvider()
    screenplay = "FADE IN:\n\nCENA 01\nINT. CASA - DIA\n\nCLARA abre a porta."

    assert provider._parse_json_content(screenplay, "generate_script") == (
        {"content": screenplay},
        "screenplay_text",
    )


def test_omniroute_llm_provider_uses_lower_temperature_for_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OmniRouteLLMProvider()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.providers.llm.omniroute.get_settings",
        lambda: Settings(
            ai_provider="omniroute",
            omniroute_api_key="omni-secret",
            omniroute_base_url="https://omnirouters.com/v1",
        ),
    )

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> _JsonResponse:
        _ = kwargs
        captured["body"] = _request_json_body(request)
        return _JsonResponse(
            {"choices": [{"message": {"content": '{"title":"T","content":"ok"}'}}]}
        )

    monkeypatch.setattr("app.providers.llm.omniroute.urllib.request.urlopen", fake_urlopen)

    provider._send_request(
        LLMRequest(task="generate_script", prompt="{}", model="provider/text-model"),
        use_response_format=True,
    )

    assert captured["body"]["temperature"] == 0.4


def test_omniroute_image_provider_writes_generated_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider = OmniRouteImageProvider()
    pixel = base64.b64encode(b"fake-png").decode("ascii")
    posted: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.providers.image.omniroute.get_settings",
        lambda: Settings(omniroute_api_key="omni-secret"),
    )

    def fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        posted.update({"path": path, "body": body})
        return {
            "data": [{"b64_json": pixel, "media_type": "image/png"}],
            "usage": {"cost": 0.02},
        }

    monkeypatch.setattr(provider, "_post_json", fake_post)

    result = provider._generate(
        ImageGenerationRequest(
            prompt="dramatic character portrait",
            target_id="char",
            view_type="front",
            output_dir=tmp_path,
            aspect_ratio="1:1",
            resolution="1080x1920",
            model="chatgpt-web/gpt-5.5",
        )
    )

    assert posted["path"] == "/images/generations"
    assert posted["body"]["aspect_ratio"] == "1:1"
    assert posted["body"]["size"] == "1080x1920"
    assert result.provider == "omniroute"
    assert result.content_type == "image/png"
    assert result.file_path.read_bytes() == b"fake-png"
    assert result.estimated_cost == "0.02"


def test_omniroute_image_provider_retries_without_response_format(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider = OmniRouteImageProvider()
    pixel = base64.b64encode(b"fake-png").decode("ascii")
    posted_bodies: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "app.providers.image.omniroute.get_settings",
        lambda: Settings(omniroute_api_key="omni-secret"),
    )

    def fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        assert path == "/images/generations"
        posted_bodies.append(dict(body))
        if len(posted_bodies) == 1:
            raise RuntimeError("OmniRoute Images HTTP 400: unsupported response_format")
        return {"data": [{"b64_json": pixel, "media_type": "image/png"}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)

    result = provider._generate(
        ImageGenerationRequest(
            prompt="dramatic character portrait",
            target_id="char",
            view_type="front",
            output_dir=tmp_path,
            model="chatgpt-web/gpt-5.5",
        )
    )

    assert "response_format" in posted_bodies[0]
    assert "response_format" not in posted_bodies[1]
    assert result.file_path.read_bytes() == b"fake-png"


def test_omniroute_image_provider_keeps_visual_references_in_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider = OmniRouteImageProvider()
    storage_root = tmp_path / "storage"
    reference_dir = storage_root / "omniroute_images"
    reference_dir.mkdir(parents=True)
    reference = reference_dir / "character.webp"
    reference.write_bytes(b"fake-reference")
    pixel = base64.b64encode(b"fake-png").decode("ascii")
    posted: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.providers.image.omniroute.get_settings",
        lambda: Settings(omniroute_api_key="omni-secret", local_storage_path=storage_root),
    )
    monkeypatch.setattr(
        "app.providers.media_utils.get_settings",
        lambda: Settings(local_storage_path=storage_root),
    )

    def fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        posted.update({"path": path, "body": body})
        return {"data": [{"b64_json": pixel, "media_type": "image/png"}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)

    provider._generate(
        ImageGenerationRequest(
            prompt="reference sheet",
            target_id="char",
            view_type="sheet",
            output_dir=tmp_path,
            references=["http://127.0.0.1:8000/storage/omniroute_images/character.webp"],
            model="chatgpt-web/gpt-5.5",
        )
    )

    reference_url = posted["body"]["input_references"][0]["image_url"]["url"]
    assert reference_url.startswith("data:image/webp;base64,")


@pytest.mark.asyncio
async def test_llm_provider_for_task_uses_omniroute_default(
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
            omniroute_api_key="omni-secret",
            omniroute_default_model="provider/text-model",
        ),
    )

    provider, model = await model_settings.llm_provider_for_task(
        object(),  # type: ignore[arg-type]
        uuid4(),
        "generate_story_ideas",
    )

    assert getattr(provider, "provider_name", None) == "omniroute"
    assert model == "provider/text-model"
