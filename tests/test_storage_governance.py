from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AssetKind
from app.storage import service as storage_service


def _settings(root: Path, max_generated_asset_bytes: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        local_storage_path=root,
        max_generated_asset_bytes=max_generated_asset_bytes,
    )


def test_resolve_storage_path_rejects_paths_outside_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    monkeypatch.setattr(storage_service, "get_settings", lambda: _settings(storage_root))

    assert storage_service.resolve_storage_path(outside.as_posix()) is None


def test_orphan_storage_files_finds_unreferenced_local_files(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    referenced = storage_root / "asset.txt"
    orphan = storage_root / "orphan.txt"
    referenced.write_text("asset", encoding="utf-8")
    orphan.write_text("orphan", encoding="utf-8")

    files = storage_service.orphan_storage_files([referenced], storage_root)

    assert [item.path for item in files] == [orphan.resolve()]
    assert files[0].size_bytes == 6


class _FakeAssetSession:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.flush_count = 0

    async def execute(self, statement: Any) -> Any:
        return SimpleNamespace(scalars=lambda: self.rows)

    async def flush(self) -> None:
        self.flush_count += 1


@pytest.mark.asyncio
async def test_cleanup_orphan_storage_files_supports_dry_run_and_effective_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    referenced = storage_root / "asset.txt"
    orphan = storage_root / "orphan.txt"
    referenced.write_text("asset", encoding="utf-8")
    orphan.write_text("orphan", encoding="utf-8")
    monkeypatch.setattr(storage_service, "get_settings", lambda: _settings(storage_root))
    session = _FakeAssetSession(
        [SimpleNamespace(storage_uri=referenced.as_posix(), project_id="project", kind="IMAGE")]
    )

    dry_run = await storage_service.cleanup_orphan_storage_files(
        cast(AsyncSession, session),
        dry_run=True,
    )
    deleted = await storage_service.cleanup_orphan_storage_files(
        cast(AsyncSession, session),
        dry_run=False,
        confirm=True,
    )

    assert dry_run.candidate_count == 1
    assert dry_run.deleted_count == 0
    assert deleted.deleted_count == 1
    assert not orphan.exists()
    assert referenced.exists()


@pytest.mark.asyncio
async def test_cleanup_orphan_storage_files_requires_confirm_for_effective_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    orphan = storage_root / "orphan.txt"
    orphan.write_text("orphan", encoding="utf-8")
    monkeypatch.setattr(storage_service, "get_settings", lambda: _settings(storage_root))
    session = _FakeAssetSession([])

    with pytest.raises(ValueError, match="confirmacao"):
        await storage_service.cleanup_orphan_storage_files(
            cast(AsyncSession, session),
            dry_run=False,
        )

    assert orphan.exists()


def test_apply_asset_storage_metadata_persists_size_and_missing_state(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    asset_path = storage_root / "asset.bin"
    asset_path.write_bytes(b"123456")
    asset = SimpleNamespace(
        storage_uri=asset_path.as_posix(),
        size_bytes=None,
        missing_at=None,
        storage_checked_at=None,
    )

    changed = storage_service.apply_asset_storage_metadata(cast(Any, asset), storage_root)

    assert changed is True
    assert asset.size_bytes == 6
    assert asset.missing_at is None
    assert asset.storage_checked_at is not None


@pytest.mark.asyncio
async def test_reconcile_local_storage_marks_missing_and_recovered_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    existing = storage_root / "image.png"
    existing.write_bytes(b"image")
    missing = storage_root / "missing.png"
    recovered_asset = SimpleNamespace(
        project_id=project_id,
        kind=AssetKind.IMAGE,
        storage_uri=existing.as_posix(),
        size_bytes=None,
        missing_at="previous",
        storage_checked_at=None,
    )
    missing_asset = SimpleNamespace(
        project_id=project_id,
        kind=AssetKind.IMAGE,
        storage_uri=missing.as_posix(),
        size_bytes=None,
        missing_at=None,
        storage_checked_at=None,
    )
    monkeypatch.setattr(storage_service, "get_settings", lambda: _settings(storage_root))
    session = _FakeAssetSession([recovered_asset, missing_asset])

    summary = await storage_service.reconcile_local_storage(
        cast(AsyncSession, session),
        project_id=project_id,
        kind="image",
    )

    assert summary.scanned_assets == 2
    assert summary.local_file_count == 1
    assert summary.missing_file_count == 1
    assert summary.recovered_file_count == 1
    assert summary.total_bytes == 5
    assert missing_asset.missing_at is not None
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_storage_usage_summary_uses_persisted_size_without_orphan_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setattr(storage_service, "get_settings", lambda: _settings(storage_root))
    monkeypatch.setattr(
        storage_service,
        "orphan_storage_files",
        lambda *_args, **_kwargs: pytest.fail("orphan scan should be explicit"),
    )
    session = _FakeAssetSession(
        [
            SimpleNamespace(
                project_id=project_id,
                kind=AssetKind.VIDEO,
                storage_uri=(storage_root / "missing.mp4").as_posix(),
                size_bytes=123,
                missing_at=None,
            )
        ]
    )

    summary = await storage_service.storage_usage_summary(cast(AsyncSession, session))

    assert summary.total_bytes == 123
    assert summary.local_file_count == 1
    assert summary.orphan_file_count == 0


def test_validate_asset_uri_size_raises_for_large_local_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    asset = storage_root / "large.bin"
    asset.write_bytes(b"12345")
    monkeypatch.setattr(
        storage_service,
        "get_settings",
        lambda: _settings(storage_root, max_generated_asset_bytes=4),
    )

    with pytest.raises(ValueError, match="excede o limite"):
        storage_service.validate_asset_uri_size(asset.as_posix())
