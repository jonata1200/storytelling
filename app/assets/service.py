from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.assets.schemas import AssetCreate
from app.projects.repository import ProjectRepository


async def create_asset(session: AsyncSession, data: AssetCreate) -> Asset | None:
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
        metadata_json=data.metadata_json,
    )
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
