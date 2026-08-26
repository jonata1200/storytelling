import re
from collections.abc import Iterable

VISUAL_PROMPT_MIN_WORDS = 20
VISUAL_PROMPT_MAX_WORDS = 65
CHARACTER_PROMPT_MIN_WORDS = 35
CHARACTER_PROMPT_MAX_WORDS = 110
LOCATION_PROMPT_MIN_WORDS = 35
LOCATION_PROMPT_MAX_WORDS = 110

_MOJIBAKE_REPLACEMENTS = {
    "\u00c3\u0080": "\u00c0",
    "\u00c3\u0081": "\u00c1",
    "\u00c3\u0082": "\u00c2",
    "\u00c3\u0083": "\u00c3",
    "\u00c3\u0087": "\u00c7",
    "\u00c3\u0089": "\u00c9",
    "\u00c3\u008a": "\u00ca",
    "\u00c3\u008d": "\u00cd",
    "\u00c3\u0093": "\u00d3",
    "\u00c3\u0094": "\u00d4",
    "\u00c3\u0095": "\u00d5",
    "\u00c3\u009a": "\u00da",
    "\u00c3\u00a0": "\u00e0",
    "\u00c3\u00a1": "\u00e1",
    "\u00c3\u00a2": "\u00e2",
    "\u00c3\u00a3": "\u00e3",
    "\u00c3\u00a7": "\u00e7",
    "\u00c3\u00a9": "\u00e9",
    "\u00c3\u00aa": "\u00ea",
    "\u00c3\u00ad": "\u00ed",
    "\u00c3\u00b3": "\u00f3",
    "\u00c3\u00b4": "\u00f4",
    "\u00c3\u00b5": "\u00f5",
    "\u00c3\u00ba": "\u00fa",
    "\u00c2\u00a0": " ",
    "\u00c2\u00aa": "\u00aa",
    "\u00c2\u00b0": "\u00b0",
    "\u00c2\u00ba": "\u00ba",
    "\u00c2\u00b7": "\u00b7",
    "\u00e2\u20ac\u201c": "\u2013",
    "\u00e2\u20ac\u201d": "\u2014",
    "\u00e2\u20ac\u0153": "\u201c",
    "\u00e2\u20ac\ufffd": "\u201d",
    "\u00e2\u20ac\u2122": "\u2019",
    "\u00e2\u20ac\u00a6": "\u2026",
}


def repair_portuguese_mojibake(value: object) -> str:
    text = str(value or "")
    for _ in range(2):
        repaired = text
        for broken, correct in _MOJIBAKE_REPLACEMENTS.items():
            repaired = repaired.replace(broken, correct)
        if repaired == text:
            break
        text = repaired
    return text


def contains_mojibake(value: object) -> bool:
    text = str(value or "")
    return "\ufffd" in text or any(broken in text for broken in _MOJIBAKE_REPLACEMENTS)


def prompt_word_count(value: object) -> int:
    return len(re.findall(r"\S+", repair_portuguese_mojibake(value).strip()))


def concise_prompt_fragment(value: object, max_words: int) -> str:
    text = re.sub(r"\s+", " ", repair_portuguese_mojibake(value)).strip(" ,;.")
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(" ,;:.")


def balanced_visual_prompt(
    parts: Iterable[object],
    *,
    max_words: int = VISUAL_PROMPT_MAX_WORDS,
) -> str:
    text = repair_portuguese_mojibake(
        re.sub(
            r"\s+",
            " ",
            " ".join(str(part or "").strip() for part in parts if str(part or "").strip()),
        ).strip()
    )
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words]).rstrip(" ,;:.") + "."
    return text
