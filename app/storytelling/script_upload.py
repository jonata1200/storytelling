import re
import zipfile
from io import BytesIO
from typing import Any
from xml.etree import ElementTree

SUPPORTED_SCRIPT_EXTENSIONS = {".pdf", ".docx"}
MAX_SCRIPT_UPLOAD_BYTES = 10 * 1024 * 1024


class ScriptUploadError(ValueError):
    pass


def extract_script_text(filename: str, content: bytes) -> str:
    extension = _extension(filename)
    if extension not in SUPPORTED_SCRIPT_EXTENSIONS:
        raise ScriptUploadError("Envie um arquivo PDF ou DOCX.")
    if len(content) > MAX_SCRIPT_UPLOAD_BYTES:
        raise ScriptUploadError("O arquivo deve ter no maximo 10 MB.")
    if extension == ".docx":
        text = _extract_docx_text(content)
    else:
        text = _extract_pdf_text(content)
    cleaned = _clean_extracted_text(text)
    if not cleaned:
        raise ScriptUploadError(
            "Nao consegui extrair texto desse arquivo. PDFs escaneados precisam de OCR."
        )
    return cleaned


def _extension(filename: str) -> str:
    lowered = filename.lower().strip()
    if "." not in lowered:
        return ""
    return "." + lowered.rsplit(".", 1)[-1]


def _extract_docx_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            document_names = [
                name
                for name in (
                    "word/document.xml",
                    "word/footnotes.xml",
                    "word/endnotes.xml",
                )
                if name in archive.namelist()
            ]
            return "\n".join(_text_from_docx_xml(archive.read(name)) for name in document_names)
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ScriptUploadError("DOCX invalido ou corrompido.") from exc


def _text_from_docx_xml(xml_content: bytes) -> str:
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ElementTree.fromstring(xml_content)
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        pieces: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{namespace}t" and node.text:
                pieces.append(node.text)
            elif node.tag == f"{namespace}tab":
                pieces.append("\t")
            elif node.tag == f"{namespace}br":
                pieces.append("\n")
        paragraph_text = "".join(pieces).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)
    return "\n".join(paragraphs)


def _extract_pdf_text(content: bytes) -> str:
    pypdf_text = _extract_pdf_with_pypdf(content)
    if pypdf_text.strip():
        return pypdf_text
    return _extract_pdf_text_fallback(content)


def _extract_pdf_with_pypdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError:
        return ""
    try:
        reader = PdfReader(BytesIO(content))
        page_text = [str(page.extract_text() or "") for page in reader.pages]
    except Exception:
        return ""
    return "\n".join(page_text)


def _extract_pdf_text_fallback(content: bytes) -> str:
    raw = content.decode("latin-1", errors="ignore")
    literal_strings = [
        _decode_pdf_literal(match.group(1))
        for match in re.finditer(r"\((.*?)\)\s*Tj", raw, flags=re.DOTALL)
    ]
    array_strings: list[str] = []
    for array_match in re.finditer(r"\[(.*?)\]\s*TJ", raw, flags=re.DOTALL):
        parts = re.findall(r"\((.*?)\)", array_match.group(1), flags=re.DOTALL)
        if parts:
            array_strings.append("".join(_decode_pdf_literal(part) for part in parts))
    hex_strings = [
        _decode_pdf_hex(match.group(1))
        for match in re.finditer(r"<([0-9A-Fa-f\s]+)>\s*Tj", raw)
    ]
    return "\n".join([*literal_strings, *array_strings, *hex_strings])


def _decode_pdf_literal(value: str) -> str:
    replacements = {
        r"\n": "\n",
        r"\r": "\n",
        r"\t": "\t",
        r"\(": "(",
        r"\)": ")",
        r"\\": "\\",
    }
    decoded = value
    for source, target in replacements.items():
        decoded = decoded.replace(source, target)
    return decoded


def _decode_pdf_hex(value: str) -> str:
    compact = re.sub(r"\s+", "", value)
    if len(compact) % 2:
        compact += "0"
    try:
        data = bytes.fromhex(compact)
    except ValueError:
        return ""
    for encoding in ("utf-16-be", "utf-8", "latin-1"):
        try:
            return data.decode(encoding).strip("\ufeff")
        except UnicodeDecodeError:
            continue
    return ""


def _clean_extracted_text(text: Any) -> str:
    normalized = str(text or "").replace("\x00", "")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()
