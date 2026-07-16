import pytest

from app.providers.llm.openrouter import OpenRouterLLMProvider


def test_openrouter_provider_parses_json_content() -> None:
    provider = OpenRouterLLMProvider()

    assert provider._parse_json_content('{"ok": true}') == {"ok": True}


def test_openrouter_provider_rejects_non_json_content() -> None:
    provider = OpenRouterLLMProvider()

    with pytest.raises(RuntimeError):
        provider._parse_json_content("nao e json")
