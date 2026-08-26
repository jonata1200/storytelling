from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactType, ProjectStatus
from app.generation.model_settings import llm_provider_for_task
from app.generation.service import run_structured_generation
from app.projects.repository import ProjectRepository
from app.storytelling.artifacts import _add_dependency, _create_artifact
from app.storytelling.models import Briefing, StoryIdea
from app.storytelling.normalization import (
    GenerationOutputError,
    _normalize_generated_story_ideas,
    _required_int,
    _required_mapping,
    _required_str,
    _story_idea_db_text,
    _story_idea_retry_guidance,
    normalize_story_idea_payload,
)
from app.workflows.state_machine import advance_project_status

SCRIPT_GENERATION_MAX_ATTEMPTS = 3

async def get_latest_briefing(session: AsyncSession, project_id: UUID) -> Briefing | None:
    result = await session.execute(
        select(Briefing)
        .where(Briefing.project_id == project_id)
        .order_by(Briefing.created_at.desc())
    )
    return result.scalars().first()


async def _story_idea_diversity_memory(session: AsyncSession, project_id: UUID) -> str:
    result = await session.execute(
        select(StoryIdea)
        .where(StoryIdea.project_id == project_id)
        .order_by(StoryIdea.created_at.desc())
        .limit(12)
    )
    ideas = list(result.scalars())
    if not ideas:
        return "nenhuma ideia anterior neste projeto"
    fragments: list[str] = []
    for idea in ideas:
        payload = idea.payload or {}
        fragments.append(
            " | ".join(
                str(value)
                for value in (
                    idea.title,
                    payload.get("protagonist") or idea.protagonist,
                    payload.get("conflict"),
                    payload.get("twist"),
                    payload.get("payoff") or payload.get("resolution"),
                )
                if value not in (None, "", [], {})
            )
        )
    return "; ".join(fragments)


async def create_story_idea_from_payload(
    session: AsyncSession, project_id: UUID, payload: dict
) -> StoryIdea | None:
    project = await ProjectRepository(session).get_project(project_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or briefing is None:
        return None

    item = normalize_story_idea_payload(payload)
    artifact = await _create_artifact(
        session,
        project_id,
        ArtifactType.STORY_IDEA,
        _story_idea_db_text(item, "title", "story_idea"),
        item,
    )
    await _add_dependency(session, briefing.artifact_id, artifact.id)
    idea = StoryIdea(
        project_id=project_id,
        artifact_id=artifact.id,
        title=_story_idea_db_text(item, "title", "story_idea"),
        hook=_required_str(item, "hook", "story_idea"),
        premise=_required_str(item, "premise", "story_idea"),
        protagonist=_story_idea_db_text(item, "protagonist", "story_idea"),
        retention_potential=_required_int(item, "retention_potential", "story_idea"),
        cliche_risk=_required_int(item, "cliche_risk", "story_idea"),
        production_complexity=_required_int(item, "production_complexity", "story_idea"),
        payload=item,
    )
    session.add(idea)
    advance_project_status(project, ProjectStatus.IDEA_APPROVAL)
    await session.commit()
    await session.refresh(idea)
    return idea


async def generate_story_ideas(session: AsyncSession, project_id: UUID) -> list[StoryIdea] | None:
    project = await ProjectRepository(session).get_project(project_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or briefing is None:
        return None

    variables = {
        "theme": briefing.theme,
        "audience": briefing.audience,
        "primary_emotion": briefing.primary_emotion,
        "genre": briefing.genre,
        "target_duration_minutes": float(briefing.desired_duration_minutes),
        "diversity_memory": await _story_idea_diversity_memory(session, project_id),
        "retry_guidance": "",
    }
    provider, model = await llm_provider_for_task(session, project_id, "generate_story_ideas")
    normalized_items: list[dict] | None = None
    last_error: GenerationOutputError | None = None
    for attempt in range(SCRIPT_GENERATION_MAX_ATTEMPTS):
        result, execution = await run_structured_generation(
            session,
            provider,
            project_id,
            "generate_story_ideas",
            variables,
            model=model,
            fallback_on_runtime_error=True,
        )
        try:
            content = _required_mapping(result.content, "generate_story_ideas")
            normalized_items = _normalize_generated_story_ideas(
                content, float(briefing.desired_duration_minutes)
            )
            execution.response = result.content
            break
        except GenerationOutputError as exc:
            last_error = exc
            if attempt < SCRIPT_GENERATION_MAX_ATTEMPTS - 1:
                variables["retry_guidance"] = _story_idea_retry_guidance([str(exc)])
                continue
            raise
    if normalized_items is None:
        if last_error is not None:
            raise last_error
        raise GenerationOutputError("generate_story_ideas: resposta vazia")

    ideas: list[StoryIdea] = []
    for index, item in enumerate(normalized_items, 1):
        artifact = await _create_artifact(
            session,
            project_id,
            ArtifactType.STORY_IDEA,
            _story_idea_db_text(item, "title", f"generate_story_ideas.ideas[{index}]"),
            item,
        )
        await _add_dependency(session, briefing.artifact_id, artifact.id)
        idea = StoryIdea(
            project_id=project_id,
            artifact_id=artifact.id,
            title=_story_idea_db_text(item, "title", f"generate_story_ideas.ideas[{index}]"),
            hook=_required_str(item, "hook", f"generate_story_ideas.ideas[{index}]"),
            premise=_required_str(item, "premise", f"generate_story_ideas.ideas[{index}]"),
            protagonist=_story_idea_db_text(
                item, "protagonist", f"generate_story_ideas.ideas[{index}]"
            ),
            retention_potential=_required_int(
                item, "retention_potential", f"generate_story_ideas.ideas[{index}]"
            ),
            cliche_risk=_required_int(item, "cliche_risk", f"generate_story_ideas.ideas[{index}]"),
            production_complexity=_required_int(
                item, "production_complexity", f"generate_story_ideas.ideas[{index}]"
            ),
            payload=item,
        )
        session.add(idea)
        ideas.append(idea)
    advance_project_status(project, ProjectStatus.IDEA_APPROVAL)
    await session.commit()
    for idea in ideas:
        await session.refresh(idea)
    return ideas


async def list_story_ideas(session: AsyncSession, project_id: UUID) -> list[StoryIdea]:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return []
    result = await session.execute(
        select(StoryIdea)
        .where(StoryIdea.project_id == project_id)
        .order_by(StoryIdea.created_at.desc())
    )
    return list(result.scalars())
