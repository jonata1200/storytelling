from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.config.settings import get_settings
from app.core.enums import AssetKind
from app.storage.schemas import (
    StorageCleanupRead,
    StorageFileRead,
    StorageProjectUsageRead,
    StorageReconciliationRead,
    StorageUsageRead,
)

REMOTE_STORAGE_PREFIXES = ("http://", "https://", "data:")


@dataclass(frozen=True)
class LocalStorageFile:
    path: Path
    size_bytes: int
    modified_at: datetime | None = None


def storage_root() -> Path:
    return get_settings().local_storage_path.resolve()


def resolve_storage_path(storage_uri: str | None, root: Path | None = None) -> Path | None:
    if not storage_uri or storage_uri.startswith(REMOTE_STORAGE_PREFIXES):
        return None
    resolved_root = (root or storage_root()).resolve()
    candidate = Path(storage_uri)
    candidates: list[Path]
    if candidate.is_absolute():
        candidates = [candidate.resolve(strict=False)]
    else:
        candidates = []
        if candidate.parts and candidate.parts[0] == resolved_root.name:
            candidates.append((resolved_root.parent / candidate).resolve(strict=False))
            candidates.append(resolved_root.joinpath(*candidate.parts[1:]).resolve(strict=False))
        candidates.extend(
            [(resolved_root / candidate).resolve(strict=False), candidate.resolve(strict=False)]
        )
    for path in candidates:
        try:
            path.relative_to(resolved_root)
        except (OSError, RuntimeError, ValueError):
            continue
        return path
    return None


def file_size_for_uri(storage_uri: str | None, root: Path | None = None) -> int | None:
    path = resolve_storage_path(storage_uri, root)
    if path is None or not path.is_file():
        return None
    return path.stat().st_size


def apply_asset_storage_metadata(
    asset: Asset,
    root: Path | None = None,
    checked_at: datetime | None = None,
) -> bool:
    checked = checked_at or datetime.now(UTC)
    path = resolve_storage_path(asset.storage_uri, root)
    previous = (asset.size_bytes, asset.missing_at, asset.storage_checked_at)
    asset.storage_checked_at = checked
    if path is None:
        asset.missing_at = None
        asset.size_bytes = None
    elif path.is_file():
        asset.size_bytes = path.stat().st_size
        asset.missing_at = None
    else:
        asset.size_bytes = None
        asset.missing_at = checked
    return previous != (asset.size_bytes, asset.missing_at, asset.storage_checked_at)


def validate_file_size(path: Path, max_bytes: int, label: str) -> None:
    if max_bytes <= 0:
        return
    size_bytes = path.stat().st_size
    if size_bytes > max_bytes:
        raise ValueError(f"{label} excede o limite de {max_bytes} bytes")


def validate_asset_uri_size(
    storage_uri: str | None,
    max_bytes: int | None = None,
    label: str = "Asset",
) -> None:
    path = resolve_storage_path(storage_uri)
    if path is None or not path.is_file():
        return
    validate_file_size(path, max_bytes or get_settings().max_generated_asset_bytes, label)


def iter_local_storage_files(root: Path | None = None) -> list[LocalStorageFile]:
    resolved_root = (root or storage_root()).resolve()
    if not resolved_root.exists():
        return []
    files: list[LocalStorageFile] = []
    for path in resolved_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(resolved_root)
            stat = resolved.stat()
        except (OSError, RuntimeError, ValueError):
            continue
        files.append(
            LocalStorageFile(
                path=resolved,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
            )
        )
    return files


def orphan_storage_files(
    referenced_paths: Iterable[Path],
    root: Path | None = None,
) -> list[LocalStorageFile]:
    resolved_root = (root or storage_root()).resolve()
    referenced = {path.resolve(strict=False) for path in referenced_paths}
    return [item for item in iter_local_storage_files(resolved_root) if item.path not in referenced]


def _normalize_kind(kind: AssetKind | str | None) -> AssetKind | None:
    if kind is None or kind == "":
        return None
    if isinstance(kind, AssetKind):
        return kind
    normalized = str(kind).strip().lower()
    for candidate in AssetKind:
        if normalized in {candidate.name.lower(), candidate.value.lower()}:
            return candidate
    raise ValueError(f"Tipo de asset desconhecido: {kind}")


async def _asset_rows(
    session: AsyncSession,
    project_id: UUID | None = None,
    kind: AssetKind | str | None = None,
) -> list[Asset]:
    statement = select(Asset)
    normalized_kind = _normalize_kind(kind)
    if project_id is not None:
        statement = statement.where(Asset.project_id == project_id)
    if normalized_kind is not None:
        statement = statement.where(Asset.kind == normalized_kind)
    result = await session.execute(statement)
    return list(result.scalars())


def _referenced_paths(assets: Iterable[Asset], root: Path) -> list[Path]:
    paths: list[Path] = []
    for asset in assets:
        path = resolve_storage_path(asset.storage_uri, root)
        if path is not None:
            paths.append(path)
    return paths


def _storage_file_read(item: LocalStorageFile) -> StorageFileRead:
    return StorageFileRead(
        path=item.path.as_posix(),
        size_bytes=item.size_bytes,
        modified_at=item.modified_at,
    )


def _kind_matches_path(item: LocalStorageFile, kind: AssetKind | None, root: Path) -> bool:
    if kind is None:
        return True
    try:
        parts = {part.lower() for part in item.path.relative_to(root).parts}
    except ValueError:
        parts = {part.lower() for part in item.path.parts}
    suffix = item.path.suffix.lower()
    if kind == AssetKind.IMAGE:
        return suffix in {".jpg", ".jpeg", ".png", ".webp"} or any(
            "visual" in part or "storyboard" in part or "reference" in part for part in parts
        )
    if kind == AssetKind.VIDEO:
        return suffix in {".mp4", ".mov", ".webm"} or any("video" in part for part in parts)
    if kind == AssetKind.AUDIO:
        return suffix in {".wav", ".mp3", ".m4a", ".aac"} or any(
            "dialogue" in part or "audio" in part or "speech" in part for part in parts
        )
    if kind == AssetKind.DOCUMENT:
        return suffix in {".json", ".txt", ".srt", ".pdf"} or any(
            "animatic" in part or "export" in part for part in parts
        )
    return True


def _orphan_matches_filters(
    item: LocalStorageFile,
    *,
    root: Path,
    project_id: UUID | None,
    kind: AssetKind | None,
    older_than_days: int | None,
) -> bool:
    if project_id is not None:
        try:
            parts = set(item.path.relative_to(root).parts)
        except ValueError:
            parts = set(item.path.parts)
        if str(project_id) not in parts:
            return False
    if not _kind_matches_path(item, kind, root):
        return False
    if older_than_days is not None:
        if item.modified_at is None:
            return False
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        if item.modified_at > cutoff:
            return False
    return True


async def storage_usage_summary(
    session: AsyncSession,
    project_id: UUID | None = None,
    *,
    include_orphans: bool = False,
) -> StorageUsageRead:
    root = storage_root()
    assets = await _asset_rows(session, project_id)
    by_project: dict[UUID, StorageProjectUsageRead] = {}
    for asset in assets:
        usage = by_project.setdefault(
            asset.project_id,
            StorageProjectUsageRead(project_id=asset.project_id),
        )
        usage.asset_count += 1
        kind = str(asset.kind.value if hasattr(asset.kind, "value") else asset.kind)
        usage.by_kind[kind] = usage.by_kind.get(kind, 0) + 1
        if asset.size_bytes is not None:
            usage.local_file_count += 1
            usage.total_bytes += int(asset.size_bytes)
        elif asset.missing_at is not None:
            usage.missing_file_count += 1

    orphan_files: list[LocalStorageFile] = []
    if include_orphans:
        all_assets = await _asset_rows(session)
        orphan_files = orphan_storage_files(_referenced_paths(all_assets, root), root)
    projects = sorted(by_project.values(), key=lambda item: str(item.project_id))
    return StorageUsageRead(
        storage_root=root,
        project_count=len(projects),
        asset_count=sum(item.asset_count for item in projects),
        local_file_count=sum(item.local_file_count for item in projects),
        missing_file_count=sum(item.missing_file_count for item in projects),
        total_bytes=sum(item.total_bytes for item in projects),
        orphan_file_count=len(orphan_files),
        orphan_total_bytes=sum(item.size_bytes for item in orphan_files),
        projects=projects,
    )


async def reconcile_local_storage(
    session: AsyncSession,
    project_id: UUID | None = None,
    kind: AssetKind | str | None = None,
) -> StorageReconciliationRead:
    root = storage_root()
    normalized_kind = _normalize_kind(kind)
    assets = await _asset_rows(session, project_id, normalized_kind)
    summary = StorageReconciliationRead(
        project_id=project_id,
        kind=normalized_kind.value if normalized_kind is not None else None,
    )
    checked_at = datetime.now(UTC)
    for asset in assets:
        was_missing = asset.missing_at is not None
        changed = apply_asset_storage_metadata(asset, root, checked_at)
        summary.scanned_assets += 1
        if asset.size_bytes is not None:
            summary.local_file_count += 1
            summary.total_bytes += int(asset.size_bytes)
            if was_missing:
                summary.recovered_file_count += 1
        elif asset.missing_at is not None:
            summary.missing_file_count += 1
        if changed:
            summary.updated_asset_count += 1
    await session.flush()
    return summary


async def list_orphan_storage_files(
    session: AsyncSession,
    *,
    project_id: UUID | None = None,
    kind: AssetKind | str | None = None,
    older_than_days: int | None = None,
) -> list[StorageFileRead]:
    root = storage_root()
    all_assets = await _asset_rows(session)
    normalized_kind = _normalize_kind(kind)
    candidates = orphan_storage_files(_referenced_paths(all_assets, root), root)
    return [
        _storage_file_read(item)
        for item in candidates
        if _orphan_matches_filters(
            item,
            root=root,
            project_id=project_id,
            kind=normalized_kind,
            older_than_days=older_than_days,
        )
    ]


async def cleanup_orphan_storage_files(
    session: AsyncSession,
    dry_run: bool = True,
    *,
    confirm: bool = False,
    project_id: UUID | None = None,
    kind: AssetKind | str | None = None,
    older_than_days: int | None = None,
) -> StorageCleanupRead:
    root = storage_root()
    candidates = await list_orphan_storage_files(
        session,
        project_id=project_id,
        kind=kind,
        older_than_days=older_than_days,
    )
    if not dry_run and not confirm:
        raise ValueError("Cleanup destrutivo exige confirmacao explicita.")
    deleted_count = 0
    deleted_total_bytes = 0
    skipped_count = 0
    if not dry_run:
        for item in candidates:
            if not _delete_orphan_candidate(item, root):
                skipped_count += 1
                continue
            deleted_count += 1
            deleted_total_bytes += item.size_bytes
    return StorageCleanupRead(
        dry_run=dry_run,
        candidate_count=len(candidates),
        candidate_total_bytes=sum(item.size_bytes for item in candidates),
        deleted_count=deleted_count,
        deleted_total_bytes=deleted_total_bytes,
        skipped_count=skipped_count,
        files=candidates,
    )


async def project_asset_storage_uris(session: AsyncSession, project_id: UUID) -> list[str]:
    result = await session.execute(select(Asset.storage_uri).where(Asset.project_id == project_id))
    return [str(row[0] or "") for row in result.all()]


def delete_local_storage_files(storage_uris: Iterable[str]) -> int:
    deleted_count = 0
    for storage_uri in storage_uris:
        path = resolve_storage_path(storage_uri)
        if path is None or not path.is_file():
            continue
        try:
            path.unlink()
        except OSError:
            continue
        deleted_count += 1
    return deleted_count


def _delete_orphan_candidate(item: StorageFileRead, root: Path) -> bool:
    path = Path(item.path).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True
