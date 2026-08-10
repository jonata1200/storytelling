import zipfile
from io import BytesIO

import pytest

from app.storytelling.script_upload import (
    ScriptUploadError,
    _read_zip_member_capped,
    extract_script_text,
)


def _minimal_docx(text: str) -> bytes:
    buffer = BytesIO()
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        "</w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def test_extract_script_text_from_docx() -> None:
    text = extract_script_text("roteiro.docx", _minimal_docx("Cena 1. A porta abre."))

    assert text == "Cena 1. A porta abre."


def test_extract_script_text_from_textual_pdf_fallback() -> None:
    pdf = b"%PDF-1.4\nBT\n(Roteiro importado pelo usuario.) Tj\nET\n%%EOF"

    text = extract_script_text("roteiro.pdf", pdf)

    assert "Roteiro importado pelo usuario." in text


def test_extract_script_text_rejects_unsupported_extensions() -> None:
    with pytest.raises(ScriptUploadError, match="PDF ou DOCX"):
        extract_script_text("roteiro.txt", b"texto")


def test_extract_script_text_rejects_pdf_without_pdf_signature() -> None:
    with pytest.raises(ScriptUploadError, match="PDF"):
        extract_script_text("roteiro.pdf", b"<html>not a pdf</html>")


def test_extract_script_text_rejects_docx_without_zip_signature() -> None:
    with pytest.raises(ScriptUploadError, match="DOCX"):
        extract_script_text("roteiro.docx", b"not a zip archive")


def test_docx_member_read_is_capped_against_zip_bomb() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "x" * 4096)
    with zipfile.ZipFile(BytesIO(buffer.getvalue())) as archive:
        with pytest.raises(ScriptUploadError, match="muito grande"):
            _read_zip_member_capped(archive, "word/document.xml", cap=1024)
