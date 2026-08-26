from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.assets.schemas import AssetCreate
from app.projects.repository import ProjectRepository
from app.storage.service import apply_asset_storage_metadata, validate_asset_uri_size


async def create_asset(session: AsyncSession, data: AssetCreate) -> Asset | None:
    validate_asset_uri_size(data.storage_uri)
    project = await ProjectRepository(session).get_project(data.project_id)
    if project is None:
        return None
    if data.artifact_id is not None:
        artifact = await ProjectRepository(session).get_artifact(data.artifact_id)
        if artifact is None or artifact.project_id != data.project_id:
            return None

    asset = Asset(
        project_id=data.project_id,
        artifact_id=data.artifact_id,
        kind=data.kind,
        name=data.name,
        storage_uri=data.storage_uri,
        content_type=data.content_type,
        sha256=data.sha256,
        size_bytes=data.size_bytes,
        metadata_json=data.metadata_json,
    )
    if asset.size_bytes is None:
        # apply_asset_storage_metadata faz I/O síncrono (path.stat); offload para
        # thread para não bloquear o event loop.
        import asyncio

        await asyncio.to_thread(apply_asset_storage_metadata, asset)
    session.add(asset)
    await session.flush()
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version_number=1,
            storage_uri=data.storage_uri,
            sha256=data.sha256,
            metadata_json=data.metadata_json,
        )
    )
    await session.commit()
    await session.refresh(asset)
    return asset
