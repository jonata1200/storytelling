"""Helpers de exportação dos storyboards (nomes de arquivo do ZIP).

Mantido puro (sem I/O) para ser reutilizado pelo endpoint de download da API
e pela UI (nome do arquivo passado ao ``ui.download``) e testável em unidade.
"""

from __future__ import annotations

import unicodedata

_SLUG_MAX_CHARS = 80


def slugify_file_part(value: object) -> str:
    """Converte um título em parte de nome de arquivo ASCII (kebab-case).

    Remove acentos, minúsculas e troca qualquer sequência inválida por "-".
    Retorna "" quando não sobra nada aproveitável.
    """
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_folded = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_folded.lower()
    slug_parts: list[str] = []
    previous_dash = True
    for char in lowered:
        if char.isalnum() and char.isascii():
            slug_parts.append(char)
            previous_dash = False
        elif not previous_dash:
            slug_parts.append("-")
            previous_dash = True
    slug = "".join(slug_parts).strip("-")
    return slug[:_SLUG_MAX_CHARS].strip("-")


def storyboard_zip_filename(project_title: object) -> str:
    """Nome do arquivo .zip do download completo dos storyboards."""
    slug = slugify_file_part(project_title) or "storyboard"
    return f"{slug}-storyboards.zip"


def storyboard_zip_entry_name(
    project_title: object,
    segment_number: int,
    segment_title: object,
    suffix: str,
) -> str:
    """Nome do arquivo dentro do ZIP: pasta do projeto + nome do segmento.

    Formato: ``<projeto>/segmento-<NN>-<titulo>.<ext>``. O número do segmento
    garante ordem e unicidade mesmo quando dois segmentos têm o mesmo título.
    """
    project_dir = slugify_file_part(project_title) or "storyboard"
    base = f"segmento-{int(segment_number):02d}"
    segment_slug = slugify_file_part(segment_title)
    if segment_slug:
        base = f"{base}-{segment_slug}"
    clean_suffix = str(suffix or "").strip().lower()
    if not clean_suffix.startswith("."):
        clean_suffix = f".{clean_suffix}" if clean_suffix else ".webp"
    return f"{project_dir}/{base}{clean_suffix}"