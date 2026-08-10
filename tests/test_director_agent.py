from app.generation.director_agent import _extract_director_message

_FALLBACK = "Posso ajudar a desenvolver esta etapa. O que deseja ajustar?"


def test_extract_director_message_prefers_message_key() -> None:
    assert _extract_director_message({"message": "Olá!"}, None) == "Olá!"


def test_extract_director_message_falls_back_to_other_keys() -> None:
    assert _extract_director_message({"response": "Resposta útil"}, None) == "Resposta útil"
    assert _extract_director_message({"answer": "Alternativa"}, None) == "Alternativa"
    assert _extract_director_message({"text": "Texto simples"}, None) == "Texto simples"


def test_extract_director_message_falls_back_to_plain_raw_content() -> None:
    assert _extract_director_message({}, "resposta em texto puro") == "resposta em texto puro"


def test_extract_director_message_does_not_dump_raw_json() -> None:
    assert _extract_director_message({}, '{"message": "ignorada"}') == _FALLBACK


def test_extract_director_message_returns_fallback_when_empty() -> None:
    assert _extract_director_message({}, None) == _FALLBACK
    assert _extract_director_message({"message": "   "}, None) == _FALLBACK
    assert _extract_director_message(None, None) == _FALLBACK
