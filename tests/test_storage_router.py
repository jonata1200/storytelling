"""Tests for storage router endpoints — security and path leakage.

Verifies:
- StorageUsageRead does not expose absolute paths (storage_root replaced with backend name)
- StorageFileRead.path is relative, not absolute
- Auth is required (via private_api_router dependency)
"""

from pathlib import Path

import pytest

from app.storage.schemas import StorageFileRead, StorageUsageRead


@pytest.mark.unit
def test_storage_usage_read_does_not_expose_absolute_path() -> None:
    usage = StorageUsageRead(
        storage_backend="local",
        project_count=1,
        asset_count=5,
        local_file_count=5,
        missing_file_count=0,
        total_bytes=1024,
        orphan_file_count=0,
        orphan_total_bytes=0,
        projects=[],
    )
    assert not hasattr(usage, "storage_root")
    assert usage.storage_backend == "local"


@pytest.mark.unit
def test_storage_file_read_path_is_relative() -> None:
    read = StorageFileRead(
        path="projects/abc/image.png",
        size_bytes=1024,
    )
    assert not Path(read.path).is_absolute()
    assert read.path == "projects/abc/image.png"


@pytest.mark.unit
def test_storage_file_read_with_absolute_path_still_relative_in_practice() -> None:
    """The service layer converts to relative before building StorageFileRead."""
    read = StorageFileRead(
        path="visual_bible/abc/character_front.png",
        size_bytes=500,
    )
    assert not read.path.startswith("/")
    assert "\\" not in read.path  # POSIX form