"""Testes das referências visuais manuais (upload e remoção)."""

import pytest

from app.visual_bible.manual_references import (
    ALLOWED_MANUAL_IMAGE_TYPES,
    MANUAL_UPLOAD_MAX_BYTES,
    ManualReferenceError,
    _validate_manual_image,
)


def test_validate_manual_image_accepts_supported_types() -> None:
    for content_type in ALLOWED_MANUAL_IMAGE_TYPES:
        _validate_manual_image(content_type, 1024)


def test_validate_manual_image_rejects_unsupported_type() -> None:
    with pytest.raises(ManualReferenceError) as excinfo:
        _validate_manual_image("application/pdf", 1024)
    assert "PNG, JPG ou WEBP" in str(excinfo.value)


def test_validate_manual_image_rejects_empty_file() -> None:
    with pytest.raises(ManualReferenceError) as excinfo:
        _validate_manual_image("image/png", 0)
    assert "vazio" in str(excinfo.value)


def test_validate_manual_image_rejects_oversized_file() -> None:
    with pytest.raises(ManualReferenceError) as excinfo:
        _validate_manual_image("image/png", MANUAL_UPLOAD_MAX_BYTES + 1)
    assert "20 MB" in str(excinfo.value)


def test_validate_manual_image_normalizes_content_type_parameters() -> None:
    _validate_manual_image("image/jpeg; charset=binary", 2048)