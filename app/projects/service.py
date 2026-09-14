from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.core.enums import ArtifactStatus, DependencyKind, ProjectStatus
from app.core.title_case import standardize_title_case
from app.generation.models import PromptExecution
from app.observability.models import OperationalEvent
from app.projects.models import Artifact, ArtifactVersion, Project, ProjectVersion
from app.projects.repository import ProjectRepository
from app.projects.schemas import ArtifactCreate, ProjectCreate
from app.projects.versioning import create_artifact_version, mark_dependents_stale
from app.storage.service import (
    delete_bridge_job_dirs,
    delete_local_storage_files,
    delete_project_storage_dirs,
)
from app.storytelling.models import Scene, Script, Shot, StoryIdea
from app.workflows.models import ArtifactDependency
from app.workflows.state_machine import assert_project_transition


async def create_project(session: AsyncSession, data: ProjectCreate) -> Project:
    # Padronização centralizada: todo título de projeto entra padronizado,
    # independente do caminho de chamada (formulário, chat, idea lab...).
    project = Project(
        title=standardize_title_case(data.title, "Novo projeto Storytelling"),
        description=data.description,
    )
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
    # Renomeação manual do usuário: padroniza também (mesma regra de criação).
    cleaned_title = standardize_title_case(title)
    if not cleaned_title:
        raise ValueError("O nome do projeto não pode ficar vazio")
    project = await session.get(Project, project_id, with_for_update=True)
    if project is None or project.deleted_at is not None:
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


async def sync_project_title(
    session: AsyncSession,
    project_id: UUID,
    title: str,
    *,
    change_note: str = "Project title synchronized",
) -> Project | None:
    # Padronização aqui (não só nos chamadores): o sync de título do roteiro
    # recebia o título cru do LLM e gravava ALL-CAPS (ex.: "O ÚLTIMO TREM").
    cleaned_title = standardize_title_case(title)[:220]
    if not cleaned_title:
        return None
    project = await session.get(Project, project_id, with_for_update=True)
    if project is None or getattr(project, "deleted_at", None) is not None:
        return None
    # Projetos criados a partir de uma ideia do laboratório têm o título
    # travado: o nome escolhido pelo usuário (ou pela ideia) não deve ser
    # sobrescrito pelo título que a IA der ao roteiro.
    if await _project_title_is_locked(session, project_id):
        return project
    if project.title.strip() == cleaned_title:
        return project
    project.title = cleaned_title
    project.current_version += 1
    session.add(
        ProjectVersion(
            project_id=project.id,
            version_number=project.current_version,
            snapshot={"title": project.title, "description": project.description},
            change_note=change_note,
        )
    )
    await session.commit()
    await session.refresh(project)
    return project


async def _project_title_is_locked(session: AsyncSession, project_id: UUID) -> bool:
    """True quando o título do projeto não deve ser sincronizado com o roteiro.

    O flag vive em ``project_production_settings.metadata_json.title_locked``,
    definido na criação de projetos a partir de ideias do laboratório.
    """
    from app.production.service import get_or_create_production_settings

    settings = await get_or_create_production_settings(session, project_id)
    metadata = settings.metadata_json if isinstance(settings.metadata_json, dict) else {}
    return bool(metadata.get("title_locked"))


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
    "DELETE FROM qa_results WHERE project_id IN (SELECT id FROM target_projects)",
    """
    DELETE FROM clip_reviews
    WHERE video_clip_id IN (
        SELECT video_clips.id
        FROM video_clips
        JOIN target_projects ON video_clips.project_id = target_projects.id
    )
    """,
    "DELETE FROM operational_events WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM video_clips WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM continuous_video_segments WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM continuous_video_plans WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM generation_jobs WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM timeline_items WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM timelines WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM animatics WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM audio_tracks WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM storyboard_frames WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM visual_references WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM characters WHERE project_id IN (SELECT id FROM target_projects)",
    "DELETE FROM locations WHERE project_id IN (SELECT id FROM target_projects)",
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
    "qa_results",
    "clip_reviews",
    "video_clips",
    "continuous_video_segments",
    "continuous_video_plans",
    "generation_jobs",
    "timeline_items",
    "timelines",
    "animatics",
    "audio_tracks",
    "storyboard_frames",
    "visual_references",
    "characters",
    "locations",
    "operational_events",
    "asset_versions",
    "assets",
    "script_versions",
    "shots",
    "scenes",
    "scripts",
    "story_ideas",
)


def _validated_table_identifiers(table_names: tuple[str, ...]) -> tuple[str, ...]:
    """Valida que cada nome é um identificador de tabela conhecido do metadata.

    Nomes de tabela não podem ser parametrizados em SQL, então qualquer
    concatenação em texto SQL exige allowlist explícita contra o metadata do
    SQLAlchemy para impedir injeção de identificadores.
    """
    from app.assets import models as asset_models  # noqa: F401
    from app.costs import models as cost_models  # noqa: F401
    from app.database.base import Base
    from app.generation import models as generation_models  # noqa: F401
    from app.observability import models as observability_models  # noqa: F401
    from app.production import models as production_models  # noqa: F401
    from app.projects import models as project_models  # noqa: F401
    from app.storyboards import models as storyboard_models  # noqa: F401
    from app.storytelling import models as storytelling_models  # noqa: F401
    from app.video_generation import models as video_generation_models  # noqa: F401
    from app.visual_bible import models as visual_bible_models  # noqa: F401
    from app.workflows import models as workflow_models  # noqa: F401

    known_tables = set(Base.metadata.tables)
    for name in table_names:
        if name not in known_tables:
            raise ValueError(f"Tabela desconhecida no metadata: {name!r}")
    return table_names


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
    import logging

    delete_logger = logging.getLogger(__name__)
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
            """,  # noqa: S608 -- TARGET_PROJECTS_CTE é constante de módulo (SQL estático), não input.
        ),
        {"project_id": project_id},
    )
    project_count = await session.scalar(text("SELECT count(*) FROM tmp_target_projects"))
    if not project_count:
        await session.rollback()
        return False
    target_project_rows = await session.execute(text("SELECT id FROM tmp_target_projects"))
    target_project_ids = [UUID(str(row[0])) for row in target_project_rows.all()]
    asset_rows = await session.execute(
        text(
            """
            SELECT storage_uri
            FROM assets
            WHERE project_id IN (SELECT id FROM tmp_target_projects)
            """
        )
    )
    asset_version_rows = await session.execute(
        text(
            """
            SELECT asset_versions.storage_uri
            FROM asset_versions
            JOIN assets ON asset_versions.asset_id = assets.id
            WHERE assets.project_id IN (SELECT id FROM tmp_target_projects)
            """
        )
    )
    asset_storage_uris = [
        str(row[0] or "") for row in [*asset_rows.all(), *asset_version_rows.all()]
    ]
    # jobIds do bridge de vídeo (diretórios storage/bridge_jobs/video/<jobId>):
    # vêm de generation_jobs.external_job_id e de continuous_video_segments
    # (external_operation_id + metadata_json.video_job_id). Coletados ANTES do
    # delete das linhas, pois o grafo é apagado em seguida.
    bridge_job_rows = await session.execute(
        text(
            """
            SELECT external_job_id
            FROM generation_jobs
            WHERE project_id IN (SELECT id FROM tmp_target_projects)
              AND external_job_id IS NOT NULL
            """
        )
    )
    segment_job_rows = await session.execute(
        text(
            """
            SELECT external_operation_id, metadata_json
            FROM continuous_video_segments
            WHERE project_id IN (SELECT id FROM tmp_target_projects)
            """
        )
    )
    bridge_job_ids: set[str] = set()
    for row in bridge_job_rows.all():
        if row[0]:
            bridge_job_ids.add(str(row[0]))
    for row in segment_job_rows.all():
        if row[0]:
            bridge_job_ids.add(str(row[0]))
        metadata = row[1] if isinstance(row[1], dict) else {}
        video_job_id = metadata.get("video_job_id")
        if video_job_id:
            bridge_job_ids.add(str(video_job_id))
    try:
        for statement in PROJECT_GRAPH_DELETE_STATEMENTS:
            await session.execute(text(statement.replace("target_projects", "tmp_target_projects")))
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    # Best-effort file deletion: DB rows are already committed, so partial
    # failure leaves orphan files (which the storage sweeper can clean up later).
    deleted_count = 0
    for storage_uri in asset_storage_uris:
        try:
            if delete_local_storage_files([storage_uri]) > 0:
                deleted_count += 1
        except OSError as exc:
            delete_logger.warning(
                "hard_delete_project_orphan_file project_id=%s uri=%s: %s",
                project_id,
                storage_uri,
                exc,
            )
    try:
        deleted_count += delete_project_storage_dirs(target_project_ids)
    except OSError as exc:
        delete_logger.warning(
            "hard_delete_project_storage_dir_failed project_id=%s: %s",
            project_id,
            exc,
        )
    try:
        deleted_count += delete_bridge_job_dirs(bridge_job_ids)
    except OSError as exc:
        delete_logger.warning(
            "hard_delete_project_bridge_job_dir_failed project_id=%s: %s",
            project_id,
            exc,
        )
    return True


async def delete_all_projects(session: AsyncSession) -> int:
    result = await session.execute(select(Project).where(Project.deleted_at.is_(None)))
    projects = list(result.scalars())
    deleted_at = datetime.now(UTC)
    for project in projects:
        project.deleted_at = deleted_at
    await session.commit()
    return len(projects)


async def hard_delete_all_projects(session: AsyncSession) -> int:
    """Exclui definitivamente todos os projetos (e seus artefatos/storage).

    Diferente de ``purge_application_data``, que trunca TODAS as tabelas da
    aplicação (incluindo ideias do laboratório e dados não vinculados a projeto),
    esta função remove apenas o grafo de cada projeto via ``hard_delete_project``.
    """
    result = await session.execute(select(Project.id).where(Project.deleted_at.is_(None)))
    project_ids = [UUID(str(row[0])) for row in result.all() if row[0]]
    deleted = 0
    for project_id in project_ids:
        if await hard_delete_project(session, project_id):
            deleted += 1
    return deleted


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


async def _all_asset_storage_uris(session: AsyncSession) -> list[str]:
    asset_result = await session.execute(select(Asset.storage_uri))
    asset_version_result = await session.execute(select(AssetVersion.storage_uri))
    rows = [*asset_result.all(), *asset_version_result.all()]
    return [str(row[0] or "") for row in rows if row[0]]


async def _all_project_ids(session: AsyncSession) -> list[UUID]:
    result = await session.execute(select(Project.id))
    return [UUID(str(row[0])) for row in result.all() if row[0]]


async def purge_application_data(session: AsyncSession) -> dict[str, int]:
    counts = await application_data_counts(session)
    project_ids = await _all_project_ids(session)
    asset_storage_uris = await _all_asset_storage_uris(session)
    await session.execute(text("TRUNCATE TABLE projects RESTART IDENTITY CASCADE"))
    await session.commit()
    counts["storage_files"] = delete_local_storage_files(asset_storage_uris)
    counts["storage_files"] += delete_project_storage_dirs(project_ids)
    return counts


async def hard_delete_all_story_ideas(session: AsyncSession) -> dict[str, int]:
    counts = await application_data_counts(session)
    asset_storage_uris = await _all_asset_storage_uris(session)
    table_list = ", ".join(_validated_table_identifiers(IDEA_GRAPH_TRUNCATE_TABLES))
    await session.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))
    for statement in NON_BRIEFING_ARTIFACT_DELETE_STATEMENTS:
        await session.execute(text(statement))
    await session.commit()
    counts["storage_files"] = delete_local_storage_files(asset_storage_uris)
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
