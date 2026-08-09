import re

PROMPT_LANGUAGE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\blive[- ]action\b", re.IGNORECASE), "cinematografico com atores reais"),
    (re.compile(r"\bimage[- ]to[- ]video\b", re.IGNORECASE), "video a partir de imagem"),
    (re.compile(r"\bsplit screen\b", re.IGNORECASE), "tela dividida"),
    (re.compile(r"\bconcept art\b", re.IGNORECASE), "arte conceitual"),
    (re.compile(r"\bcartoon\b", re.IGNORECASE), "desenho caricato"),
    (re.compile(r"\b3d render\b", re.IGNORECASE), "renderizacao 3D"),
    (re.compile(r"\breference sheet\b", re.IGNORECASE), "folha de referencia"),
    (re.compile(r"\bfront portrait\b", re.IGNORECASE), "retrato frontal"),
    (re.compile(r"\bfull body\b", re.IGNORECASE), "corpo inteiro"),
    (re.compile(r"\bback view\b", re.IGNORECASE), "vista de costas"),
    (re.compile(r"\bside view\b", re.IGNORECASE), "vista lateral"),
    (re.compile(r"\bestablishing shot\b", re.IGNORECASE), "plano geral de ambientacao"),
    (re.compile(r"\bprops\b", re.IGNORECASE), "objetos de cena"),
    (re.compile(r"\bprop\b", re.IGNORECASE), "objeto de cena"),
    (re.compile(r"\blayout\b", re.IGNORECASE), "organizacao espacial"),
    (re.compile(r"\bUI\b"), "interface visual"),
    (re.compile(r"\blabels\b", re.IGNORECASE), "rotulos"),
    (re.compile(r"\bfemale\b", re.IGNORECASE), "feminino"),
    (re.compile(r"\bwoman\b", re.IGNORECASE), "mulher"),
    (re.compile(r"\bmale\b", re.IGNORECASE), "masculino"),
    (re.compile(r"\bman\b", re.IGNORECASE), "homem"),
    (re.compile(r"\bexpressive detective\b", re.IGNORECASE), "detetive expressiva"),
    (re.compile(r"\brainy noir lighting\b", re.IGNORECASE), "iluminacao noir chuvosa"),
)


def ensure_portuguese_prompt_text(value: object) -> str:
    text = str(value or "").strip()
    for pattern, replacement in PROMPT_LANGUAGE_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def formatted_prompt_sections(sections: list[tuple[str, object]]) -> str:
    lines: list[str] = []
    for title, body in sections:
        body_text = ensure_portuguese_prompt_text(body)
        if not body_text:
            continue
        if lines:
            lines.append("")
        lines.append(f"{title}:")
        lines.append(body_text)
    return "\n".join(lines).strip()
