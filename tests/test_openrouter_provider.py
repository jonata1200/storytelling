import urllib.error

import pytest

from app.providers.llm.openrouter import OpenRouterLLMProvider
from app.providers.llm.types import LLMRequest


def test_openrouter_provider_parses_json_content() -> None:
    provider = OpenRouterLLMProvider()

    assert provider._parse_json_content('{"ok": true}') == {"ok": True}


def test_openrouter_provider_parses_markdown_json_block() -> None:
    provider = OpenRouterLLMProvider()

    assert provider._parse_json_content('```json\n{"ideas": []}\n```') == {"ideas": []}


def test_openrouter_provider_rejects_non_json_content() -> None:
    provider = OpenRouterLLMProvider()

    with pytest.raises(RuntimeError):
        provider._parse_json_content("nao e json")


def test_openrouter_provider_reports_api_error_without_choices() -> None:
    provider = OpenRouterLLMProvider()

    with pytest.raises(RuntimeError, match="limite"):
        provider._extract_message_content({"error": {"message": "limite de uso atingido"}})


def test_openrouter_provider_rejects_response_without_choices() -> None:
    provider = OpenRouterLLMProvider()

    with pytest.raises(RuntimeError, match="sem choices"):
        provider._extract_message_content({"id": "abc", "model": "teste"})


def test_openrouter_provider_reports_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenRouterLLMProvider()

    class Settings:
        openrouter_api_key = "sk-or-v1-test"
        openrouter_base_url = "https://openrouter.ai/api/v1"
        openrouter_site_url = "http://127.0.0.1:8000"
        openrouter_app_title = "Storytelling"

    def raise_url_error(*args: object, **kwargs: object) -> None:
        raise urllib.error.URLError("temporary failure in name resolution")

    monkeypatch.setattr("app.providers.llm.openrouter.get_settings", lambda: Settings())
    monkeypatch.setattr("app.providers.llm.openrouter.urllib.request.urlopen", raise_url_error)

    with pytest.raises(RuntimeError, match="network error"):
        provider._send_request(
            LLMRequest(task="generate_story_ideas", prompt="{}", model="model"),
            use_response_format=True,
        )


def test_openrouter_provider_rejects_invalid_api_key_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenRouterLLMProvider()

    class Settings:
        openrouter_api_key = "JKl1464&*"
        openrouter_base_url = "https://openrouter.ai/api/v1"
        openrouter_site_url = "http://127.0.0.1:8000"
        openrouter_app_title = "Storytelling"

    monkeypatch.setattr("app.providers.llm.openrouter.get_settings", lambda: Settings())

    with pytest.raises(RuntimeError, match="ausente ou invalida"):
        provider._send_request(
            LLMRequest(task="generate_story_ideas", prompt="{}", model="model"),
            use_response_format=True,
        )
