import re

from app.generation.project_agent_visual import _normalize_match_text


def _is_ai_generation_failure_message(message: str) -> bool:
    normalized = message.casefold()
    return any(
        marker in normalized
        for marker in (
            "não consegui",
            "nao consegui",
            "não foi gerado",
            "nao foi gerado",
            "não foram gerados",
            "nao foram gerados",
        )
    )


def _is_visual_reference_gate_message(message: str) -> bool:
    return message.startswith("Conclua a Biblioteca Visual")


def _requests_specific_script_scenes(message: str) -> bool:
    normalized = _normalize_match_text(message)
    return bool(
        any(term in normalized for term in ("cena", "cenas", "scene", "scenes"))
        and re.search(r"\b(?:cena|cenas|scene|scenes)\s+\d+", normalized)
    )


def _requested_storyboard_scene_number(message: str) -> int | None:
    normalized = _normalize_match_text(message)
    match = re.search(
        r"\b(?:cena|scene)\s*(?:numero|n|no)?\s*0*([1-9]\d*)\b",
        normalized,
    )
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _requests_full_script_regeneration(message: str) -> bool:
    normalized = _normalize_match_text(message)
    if not any(term in normalized for term in ("roteiro", "script")):
        return False
    if _requests_specific_script_scenes(message):
        return False
    full_terms = (
        "roteiro completo",
        "roteiro inteiro",
        "roteiro todo",
        "todo o roteiro",
        "script completo",
        "script inteiro",
        "do zero",
        "novo roteiro",
        "roteiro novo",
        "nova versao",
        "nova versão",
        "gerar novamente",
        "gere novamente",
        "regenerar",
        "refazer tudo",
        "refaca tudo",
        "reescrever tudo",
    )
    return any(term in normalized for term in full_terms)
