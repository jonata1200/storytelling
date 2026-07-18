from pathlib import Path

import pytest

from app.ui.pages import _save_script_upload


def test_script_upload_accepts_pdf_and_docx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    pdf = _save_script_upload("meu roteiro.pdf", b"%PDF")
    docx = _save_script_upload("meu roteiro.docx", b"PK")

    assert pdf == Path("storage/uploads/scripts/meu_roteiro.pdf")
    assert docx == Path("storage/uploads/scripts/meu_roteiro.docx")
    assert pdf.read_bytes() == b"%PDF"
    assert docx.read_bytes() == b"PK"


def test_script_upload_rejects_other_extensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="nao permitido"):
        _save_script_upload("roteiro.txt", b"texto")
