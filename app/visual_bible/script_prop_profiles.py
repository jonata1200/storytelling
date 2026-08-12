import re

from app.visual_bible.script_profiles import (
    _append_metadata as _append_metadata,
)
from app.visual_bible.script_profiles import (
    _ascii_lower,
    _candidate_importance,
    _clean_script_entity_name,
    _entity_key,
    _parse_script_scenes,
)

SCRIPT_PROP_KEYWORDS = (
    "anel",
    "bilhete",
    "boneca",
    "brinquedo",
    "caderno",
    "cachimbo",
    "caixa",
    "caneta",
    "carta",
    "chave",
    "chocalho",
    "colher",
    "colar",
    "corda",
    "cristal",
    "cristais",
    "cumbuca",
    "diario",
    "desenho",
    "envelope",
    "espelho",
    "espelhos",
    "esfera",
    "esferas",
    "faca",
    "fita",
    "flauta",
    "fotografia",
    "frasco",
    "frascos",
    "girassol",
    "lapide",
    "lapides",
    "lápide",
    "lápides",
    "livro",
    "livros",
    "mala",
    "mochila",
    "panela",
    "partitura",
    "pote",
    "prato",
    "receita",
    "relogio",
    "relógio",
    "retrato",
    "tabua",
    "tambor",
    "violino",
)

SCRIPT_MAIN_PROP_EVIDENCE_RE = re.compile(
    r"\b("
    r"abre|acende|apaga|aperta|aponta|carrega|coloca|constroi|constroem|"
    r"desenha|destranca|entrega|encontra|esconde|escreve|fecha|folheia|"
    r"guarda|le|levanta|mexe|mistura|mostra|mostram|pega|puxa|quebra|queima|"
    r"rasga|recebe|revela|segura|tira|toca|tranca|traz|usa|utiliza|"
    r"central|climax|destaque|importante|payoff|pista|principal|prova|"
    r"recorrente|revelacao|ritual|segredo|virada"
    r")\b",
    re.IGNORECASE,
)


def _clean_script_prop_name(value: str) -> str:
    text = _clean_script_entity_name(value)
    text = re.split(
        r"(?i)\s+(?:e|ou|que|eh|é|está|está|fica|parece|ve|vê|olha|pega|segura|sai|entra)\b",
        text,
        maxsplit=1,
    )[0]
    text = re.split(
        r"(?i)\s+(?:no|na|nos|nas)\s+"
        r"(?:chao|chão|mesa|parede|bolso|mao|mão|mãos|mãos|ar|torre)\b",
        text,
        maxsplit=1,
    )[0]
    text = re.split(
        r"(?i)\s+(?:ao|aos|à|às|a)\s+(?:seu|sua|seus|suas|dele|dela|deles|delas)\b",
        text,
        maxsplit=1,
    )[0]
    return re.sub(r"\s+", " ", text).strip(" .:-")


def _prop_family_key(name: str) -> str:
    words = str(name or "").split()
    key = _entity_key(words[0] if words else name)
    for suffix in ("oes", "aes", "ais", "eis", "is", "es", "s"):
        if len(key) > len(suffix) + 3 and key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def _script_prop_profile(
    name: str, scene_number: int | None = None, evidence_text: str = ""
) -> dict:
    return {
        "name": name,
        "narrative_importance": f"Objeto narrativo extraido do roteiro: {name}",
        "material": "material visivel conforme descrito no roteiro",
        "state": "estado coerente com a cena em que aparece",
        "scene_numbers": [scene_number] if scene_number is not None else [],
        "evidence_text": [evidence_text] if evidence_text else [],
        "importance": _candidate_importance(1, scene_number or 999),
    }


def _prop_search_blocks(script_content: str) -> list[tuple[int | None, str]]:
    scenes = _parse_script_scenes(script_content)
    if not scenes:
        return [(None, script_content)]
    return [(scene.scene_number, scene.block) for scene in scenes]


def _prop_evidence_text(block: str, start: int, end: int) -> str:
    sentence_start = max(block.rfind(".", 0, start), block.rfind("\n", 0, start))
    sentence_end_candidates = [
        index for index in (block.find(".", end), block.find("\n", end)) if index != -1
    ]
    sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(block)
    evidence = block[sentence_start + 1 : sentence_end].strip()
    return re.sub(r"\s+", " ", evidence)[:240]


def _script_prop_has_main_evidence(evidence_text: str) -> bool:
    normalized = _ascii_lower(evidence_text)
    return bool(SCRIPT_MAIN_PROP_EVIDENCE_RE.search(normalized))


def _script_prop_profiles(script_content: str) -> list[dict]:
    profiles: list[dict] = []
    seen: set[str] = set()
    seen_families: set[str] = set()
    search_blocks = _prop_search_blocks(script_content)
    for keyword in SCRIPT_PROP_KEYWORDS:
        pattern = re.compile(
            rf"\b(?:um|uma|o|a|os|as|do|da|dos|das)?\s*"
            rf"((?:\w+\s+){{0,2}}\b{re.escape(keyword)}\b"
            r"(?:\s+(?!de\b|do\b|da\b|dos\b|das\b|com\b)\w+){0,2}"
            r"(?:\s+(?:de|do|da|dos|das|com)\s+\w+(?:\s+\w+){0,3})?)",
            re.IGNORECASE,
        )
        for scene_number, block in search_blocks:
            match = pattern.search(block)
            if match is None:
                continue
            raw_name = match.group(1)
            keyword_match = re.search(rf"\b{re.escape(keyword)}\b", raw_name, re.IGNORECASE)
            if keyword_match is not None:
                raw_name = raw_name[keyword_match.start() :]
            name = _clean_script_prop_name(raw_name)
            if not name or len(name) < 3:
                continue
            evidence_text = _prop_evidence_text(block, match.start(1), match.end(1))
            if not _script_prop_has_main_evidence(evidence_text):
                continue
            key = _entity_key(name)
            if key in seen:
                continue
            family_key = _prop_family_key(name)
            if family_key in seen_families:
                continue
            seen.add(key)
            seen_families.add(family_key)
            profiles.append(
                _script_prop_profile(
                    name,
                    scene_number,
                    evidence_text,
                )
            )
            break
        if len(profiles) >= 6:
            break
    return profiles
