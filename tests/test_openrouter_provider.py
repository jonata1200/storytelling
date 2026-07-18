import pytest

from app.providers.llm.openrouter import OpenRouterLLMProvider


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
