"""Padronização de caixa de títulos (PT-BR) — lógica pura, sem dependências de UI.

Módulo canônico da regra de padronização: `app.projects.service` aplica na
criação/renomeação/sincronização do título do projeto para que NENHUM caminho
de escrita precise lembrar de chamar a padronização por conta própria
(brecha histórica: sync de título do roteiro gravava "O ÚLTIMO TREM" cru).
"""

import re

# Palavras que ficam em minúsculas em títulos padronizados (padrão editorial PT-BR),
# exceto quando abrem o título.
PT_TITLE_MINOR_WORDS = frozenset(
    {
        "a", "as", "o", "os", "um", "uma", "uns", "umas",
        "de", "do", "da", "dos", "das",
        "e", "ou", "nem", "mas", "que",
        "em", "no", "na", "nos", "nas",
        "por", "pelo", "pela", "pelos", "pelas",
        "com", "sem", "para", "à", "ao", "aos", "às",
        "sobre", "entre", "até", "desde", "ante", "sob",
    }
)

# Siglas e formas que devem manter caixa alta intacta.
PT_TITLE_KEEP_UPPER = frozenset({"uf", "tv", "ovni", "pdf", "kg", "km", "mm", "cm"})

_CAPITALIZE_AFTER = (":", "-", "–", "—")


def standardize_title_case(value: object, fallback: str = "") -> str:
    """Padroniza o caso de um título: capitaliza palavras significativas,
    mantém artigos/preposições em minúsculas (exceto na abertura) e preserva
    siglas. Colapsa TUDO-EM-MAIÚSCULAS para caixa natural."""
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return fallback
    words = text.split(" ")
    fully_upper = text == text.upper() and any(char.isalpha() for char in text)
    normalized_words: list[str] = []
    for index, word in enumerate(words):
        lowered = word.casefold()
        if lowered in PT_TITLE_KEEP_UPPER:
            normalized_words.append(word.upper())
            continue
        previous = normalized_words[-1] if normalized_words else ""
        starts_segment = previous.endswith((":", "-", "–", "—"))
        if fully_upper or word.isupper():
            word = lowered
        if index > 0 and not starts_segment and lowered in PT_TITLE_MINOR_WORDS:
            normalized_words.append(lowered)
            continue
        normalized_words.append(lowered[:1].upper() + lowered[1:] if lowered else word)
    standardized = " ".join(normalized_words)
    return standardized or fallback


def strip_idea_title_prefix(value: object) -> str:
    """Remove o prefixo "Ideia NN:"/"Ideia NN -" antes da padronização."""
    return re.sub(r"^\s*ideia\s+\d+\s*[:\-–]\s*", "", str(value or ""), flags=re.IGNORECASE).strip()


def clean_idea_title(value: object, fallback: str = "História sem título") -> str:
    title = strip_idea_title_prefix(value)
    return standardize_title_case(title, fallback)