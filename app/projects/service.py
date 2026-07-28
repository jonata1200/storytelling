from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.core.enums import ArtifactStatus, DependencyKind, ProjectStatus
from app.generation.models import PromptExecution
from app.observability.models import OperationalEvent
from app.projects.models import Artifact, ArtifactVersion, Project, ProjectVersion
from app.projects.repository import ProjectRepository
from app.projects.schemas import ArtifactCreate, ProjectCreate
from app.projects.versioning import create_artifact_version, mark_dependents_stale
from app.storage.service import delete_local_storage_files
from app.storytelling.models import Scene, Script, Shot, StoryIdea
from app.workflows.models import ArtifactDependency
from app.workflows.state_machine import assert_project_transition


async def create_project(session: AsyncSession, data: ProjectCreate) -> Project:
    project = Project(title=data.title, description=data.description)
    session.add(project)
    await session.flush()

    version = ProjectVersion(
        project_id=project.id,
        version_number=1,
        snapshot={"title": project.title, "description": project.description},
        change_note="Initial project version",
    )
    session.add(version)
    await session.commit()
    await session.refresh(project)
    return project


async def list_projects(session: AsyncSession) -> list[Project]:
    return await ProjectRepository(session).list_projects()


async def rename_project(session: AsyncSession, project_id: UUID, title: str) -> Project | None:
    cleaned_title = title.strip()
    if not cleaned_title:
        raise ValueError("O nome do projeto não pode ficar vazio")
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return None
    project.title = cleaned_title[:220]
    project.current_version += 1
    session.add(
        ProjectVersion(
            project_id=project.id,
            version_number=project.current_version,
            snapshot={"title": project.title, "description": project.description},
            change_note="Project renamed",
        )
    )
    await session.commit()
    await session.refresh(project)
    return project


async def delete_project(session: AsyncSession, project_id: UUID) -> bool:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return False
    project.deleted_at = datetime.now(UTC)
    await session.commit()
    return True


TARGET_PROJECTS_CTE = """
WITH RECURSIVE target_projects(id) AS (
    SELECT id
    FROM projects
    WHERE id = :project_id
    UNION
    SELECT project_production_settings.project_id
    FROM project_production_settings
    JOIN target_projects
        ON project_production_settings.parent_project_id = target_projects.id
)
"""


PROJECT_GRAPH_DELETE_STATEMENTS = (
    """
    DELETE FROM clip_reviews
    WHERE video_clip_id IN (
        SELECT video_clips.id
        FROM video_clips
        JOIN target_projects ON video_clips.project_id = target_projects.id
    )
    """,
    "DELETE FROM operational_events WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM exports WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM subtitle_tracks WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM video_clips WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM generation_jobs WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM continuity_issues WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM continuity_states WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM quality_checks WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM timeline_items WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM timelines WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM animatics WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM audio_tracks WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM storyboard_frames WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM visual_references WHERE project_id IN (SELECT id FROM target_projects)",
    """
    DELETE FROM character_versions
    WHERE character_id IN (
        SELECT characters.id
        FROM characters
        JOIN target_projects ON characters.project_id = target_projects.id
    )
    """,
    "DELETE FROM characters WHERE project_id IN (SELECT id FROM target_projects)",
    """
    DELETE FROM location_versions
    WHERE location_id IN (
        SELECT locations.id
        FROM locations
        JOIN target_projects ON locations.project_id = target_projects.id
    )
    """,
    "DELETE FROM locations WHERE project_id IN (SELECT id FROM target_projects)",
    """
    DELETE FROM prop_versions
    WHERE prop_id IN (
        SELECT props.id
        FROM props
        JOIN target_projects ON props.project_id = target_projects.id
    )
    """,
    "DELETE FROM props WHERE project_id IN (SELECT id FROM target_projects)",
    """
    DELETE FROM asset_versions
    WHERE asset_id IN (
        SELECT assets.id
        FROM assets
        JOIN target_projects ON assets.project_id = target_projects.id
    )
    """,
    "DELETE FROM assets WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM cost_entries WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM prompt_executions WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM project_model_settings WHERE project_id IN (SELECT id FROM target_projects)",
    """
    DELETE FROM project_production_settings
    WHERE project_id IN (SELECT id FROM target_projects)
       OR parent_project_id IN (SELECT id FROM target_projects)
    """,
    """
    DELETE FROM artifact_dependencies
    WHERE upstream_artifact_id IN (
        SELECT artifacts.id
        FROM artifacts
        JOIN target_projects ON artifacts.project_id = target_projects.id
    )
       OR downstream_artifact_id IN (
        SELECT artifacts.id
        FROM artifacts
        JOIN target_projects ON artifacts.project_id = target_projects.id
    )
    """,
    """
    DELETE FROM approvals
    WHERE artifact_id IN (
        SELECT artifacts.id
        FROM artifacts
        JOIN target_projects ON artifacts.project_id = target_projects.id
    )
       OR artifact_version_id IN (
        SELECT artifact_versions.id
        FROM artifact_versions
        JOIN artifacts ON artifact_versions.artifact_id = artifacts.id
        JOIN target_projects ON artifacts.project_id = target_projects.id
    )
    """,
    """
    DELETE FROM script_versions
    WHERE script_id IN (
        SELECT scripts.id
        FROM scripts
        JOIN target_projects ON scripts.project_id = target_projects.id
    )
    """,
    "DELETE FROM shots WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM scenes WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM scripts WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM story_ideas WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM briefings WHERE project_id IN (SELECT id FROM target_projects)",
    """
    DELETE FROM artifact_versions
    WHERE artifact_id IN (
        SELECT artifacts.id
        FROM artifacts
        JOIN target_projects ON artifacts.project_id = target_projects.id
    )
    """,
    "DELETE FROM artifacts WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM project_versions WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM projects WHERE id IN (SELECT id FROM target_projects)",
)


IDEA_GRAPH_TRUNCATE_TABLES = (
    "clip_reviews",
    "exports",
    "subtitle_tracks",
    "video_clips",
    "generation_jobs",
    "continuity_issues",
    "continuity_states",
    "quality_checks",
    "timeline_items",
    "timelines",
    "animatics",
    "audio_tracks",
    "storyboard_frames",
    "visual_references",
    "character_versions",
    "characters",
    "location_versions",
    "locations",
    "prop_versions",
    "props",
    "operational_events",
    "asset_versions",
    "assets",
    "script_versions",
    "shots",
    "scenes",
    "scripts",
    "story_ideas",
)


NON_BRIEFING_ARTIFACT_DELETE_STATEMENTS = (
    """
    DELETE FROM approvals
    WHERE artifact_id IN (SELECT id FROM artifacts WHERE artifact_type <> 'BRIEFING')
       OR artifact_version_id IN (
        SELECT artifact_versions.id
        FROM artifact_versions
        JOIN artifacts ON artifact_versions.artifact_id = artifacts.id
        WHERE artifacts.artifact_type <> 'BRIEFING'
    )
    """,
    """
    DELETE FROM artifact_dependencies
    WHERE upstream_artifact_id IN (SELECT id FROM artifacts WHERE artifact_type <> 'BRIEFING')
       OR downstream_artifact_id IN (SELECT id FROM artifacts WHERE artifact_type <> 'BRIEFING')
    """,
    """
    DELETE FROM operational_events
    WHERE artifact_id IN (SELECT id FROM artifacts WHERE artifact_type <> 'BRIEFING')
    """,
    """
    DELETE FROM cost_entries
    WHERE artifact_id IN (SELECT id FROM artifacts WHERE artifact_type <> 'BRIEFING')
    """,
    """
    DELETE FROM prompt_executions
    WHERE artifact_id IN (SELECT id FROM artifacts WHERE artifact_type <> 'BRIEFING')
    """,
    """
    DELETE FROM artifact_versions
    WHERE artifact_id IN (SELECT id FROM artifacts WHERE artifact_type <> 'BRIEFING')
    """,
    "DELETE FROM artifacts WHERE artifact_type <> 'BRIEFING'",
)


async def hard_delete_project(session: AsyncSession, project_id: UUID) -> bool:
    await session.execute(text("DROP TABLE IF EXISTS tmp_target_projects"))
    await session.execute(
        text(
            """
            CREATE TEMP TABLE tmp_target_projects (
                id uuid PRIMARY KEY
            ) ON COMMIT DROP
            """
        )
    )
    await session.execute(
        text(
            f"""
            INSERT INTO tmp_target_projects (id)
            {TARGET_PROJECTS_CTE}
            SELECT id FROM target_projects
            """
        ),
        {"project_id": project_id},
    )
    project_count = await session.scalar(text("SELECT count(*) FROM tmp_target_projects"))
    if not project_count:
        await session.rollback()
        return False
    asset_rows = await session.execute(
        text(
            """
            SELECT storage_uri
            FROM assets
            WHERE project_id IN (SELECT id FROM tmp_target_projects)
            """
        )
    )
    asset_storage_uris = [str(row[0] or "") for row in asset_rows.all()]
    for statement in PROJECT_GRAPH_DELETE_STATEMENTS:
        await session.execute(text(statement.replace("target_projects", "tmp_target_projects")))
    await session.commit()
    delete_local_storage_files(asset_storage_uris)
    return True


async def delete_all_projects(session: AsyncSession) -> int:
    result = await session.execute(select(Project).where(Project.deleted_at.is_(None)))
    projects = list(result.scalars())
    deleted_at = datetime.now(UTC)
    for project in projects:
        project.deleted_at = deleted_at
    await session.commit()
    return len(projects)


APPLICATION_DATA_COUNT_MODELS = (
    Project,
    Artifact,
    StoryIdea,
    Script,
    Scene,
    Shot,
    Asset,
    PromptExecution,
    OperationalEvent,
)


async def application_data_counts(session: AsyncSession) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model in APPLICATION_DATA_COUNT_MODELS:
        value = await session.scalar(select(func.count()).select_from(model))
        counts[model.__tablename__] = int(value or 0)
    return counts


async def purge_application_data(session: AsyncSession) -> dict[str, int]:
    counts = await application_data_counts(session)
    await session.execute(text("TRUNCATE TABLE projects RESTART IDENTITY CASCADE"))
    await session.commit()
    return counts


async def hard_delete_all_story_ideas(session: AsyncSession) -> dict[str, int]:
    counts = await application_data_counts(session)
    table_list = ", ".join(IDEA_GRAPH_TRUNCATE_TABLES)
    await session.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))
    for statement in NON_BRIEFING_ARTIFACT_DELETE_STATEMENTS:
        await session.execute(text(statement))
    await session.commit()
    return counts


async def hard_delete_story_idea_by_payload_id(session: AsyncSession, idea_id: str) -> bool:
    return await hard_delete_story_idea_by_payload_id_status(session, idea_id) == "deleted"


async def hard_delete_story_idea_by_payload_id_status(
    session: AsyncSession,
    idea_id: str,
) -> str:
    story_idea = await session.scalar(
        select(StoryIdea).where(StoryIdea.payload["id"].as_string() == idea_id).limit(1)
    )
    if story_idea is None:
        return "not_found"
    script_count = await session.scalar(
        select(func.count()).select_from(Script).where(Script.story_idea_id == story_idea.id)
    )
    if script_count:
        return "blocked"
    await session.execute(
        text(
            """
            DELETE FROM approvals
            WHERE artifact_id = :artifact_id
               OR artifact_version_id IN (
                SELECT id FROM artifact_versions WHERE artifact_id = :artifact_id
            )
            """
        ),
        {"artifact_id": story_idea.artifact_id},
    )
    await session.execute(
        text(
            """
            DELETE FROM artifact_dependencies
            WHERE upstream_artifact_id = :artifact_id
               OR downstream_artifact_id = :artifact_id
            """
        ),
        {"artifact_id": story_idea.artifact_id},
    )
    await session.execute(
        text("DELETE FROM cost_entries WHERE artifact_id = :artifact_id"),
        {"artifact_id": story_idea.artifact_id},
    )
    await session.execute(
        text("DELETE FROM prompt_executions WHERE artifact_id = :artifact_id"),
        {"artifact_id": story_idea.artifact_id},
    )
    await session.execute(
        text("DELETE FROM story_ideas WHERE id = :story_idea_id"),
        {"story_idea_id": story_idea.id},
    )
    await session.execute(
        text("DELETE FROM artifact_versions WHERE artifact_id = :artifact_id"),
        {"artifact_id": story_idea.artifact_id},
    )
    await session.execute(
        text("DELETE FROM artifacts WHERE id = :artifact_id"),
        {"artifact_id": story_idea.artifact_id},
    )
    await session.commit()
    return "deleted"


async def create_artifact(
    session: AsyncSession, project_id: UUID, data: ArtifactCreate
) -> Artifact | None:
    project = await session.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        return None

    artifact = Artifact(
        project_id=project_id,
        artifact_type=data.artifact_type,
        name=data.name,
        status=ArtifactStatus.READY_FOR_REVIEW if data.payload else ArtifactStatus.PENDING,
    )
    session.add(artifact)
    await session.flush()
    session.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version_number=1,
            payload=data.payload,
            change_note="Initial artifact version",
        )
    )
    await session.commit()
    await session.refresh(artifact)
    return artifact


async def transition_project_status(
    session: AsyncSession, project_id: UUID, target_status: ProjectStatus
) -> Project | None:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return None
    assert_project_transition(project.status, target_status)
    project.status = target_status
    await session.commit()
    await session.refresh(project)
    return project


async def add_artifact_version(
    session: AsyncSession,
    artifact_id: UUID,
    payload: dict,
    change_note: str | None = None,
) -> ArtifactVersion | None:
    artifact = await ProjectRepository(session).get_artifact(artifact_id)
    if artifact is None:
        return None
    version = await create_artifact_version(session, artifact, payload, change_note)
    await session.commit()
    await session.refresh(version)
    return version


async def add_artifact_dependency(
    session: AsyncSession,
    upstream_artifact_id: UUID,
    downstream_artifact_id: UUID,
    dependency_kind: DependencyKind,
) -> ArtifactDependency | None:
    repository = ProjectRepository(session)
    upstream = await repository.get_artifact(upstream_artifact_id)
    downstream = await repository.get_artifact(downstream_artifact_id)
    if upstream is None or downstream is None:
        return None
    if upstream.project_id != downstream.project_id or upstream.id == downstream.id:
        return None

    dependency = ArtifactDependency(
        upstream_artifact_id=upstream_artifact_id,
        downstream_artifact_id=downstream_artifact_id,
        dependency_kind=dependency_kind,
    )
    session.add(dependency)
    await session.commit()
    await session.refresh(dependency)
    return dependency


async def stale_dependents_for_artifact(session: AsyncSession, artifact_id: UUID) -> set[UUID]:
    stale_ids = await mark_dependents_stale(session, {artifact_id})
    await session.commit()
    return stale_ids
