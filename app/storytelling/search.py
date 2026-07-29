from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects.repository import ProjectRepository
from app.search_filters import filter_ideas
from app.storytelling.models import StoryIdea


def _idea_payload(idea: StoryIdea) -> dict[str, object]:
    payload = idea.payload if isinstance(idea.payload, dict) else {}
    return {
        "id": idea.id,
        "title": idea.title,
        "theme": payload.get("theme"),
        "hook": idea.hook,
        "premise": idea.premise,
        "protagonist": idea.protagonist,
        "genre": payload.get("genre"),
        "primary_emotion": payload.get("primary_emotion"),
        "duration_minutes": payload.get("duration_minutes"),
        "retention_potential": idea.retention_potential,
        "cliche_risk": idea.cliche_risk,
        "production_complexity": idea.production_complexity,
        "created_at": idea.created_at,
    }


async def search_story_ideas(
    session: AsyncSession,
    project_id: UUID,
    *,
    query: str | None = None,
    genre_filter: str = "all",
    emotion_filter: str = "all",
    duration_filter: object = "all",
    complexity_filter: str = "all",
    sort: str = "created_desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[StoryIdea], int]:
    if await ProjectRepository(session).get_project(project_id) is None:
        return [], 0
    result = await session.execute(
        select(StoryIdea)
        .where(StoryIdea.project_id == project_id)
        .order_by(StoryIdea.created_at.desc(), StoryIdea.id.desc())
    )
    ideas = list(result.scalars())
    idea_by_id = {idea.id: idea for idea in ideas}
    filtered_payloads = filter_ideas(
        [_idea_payload(idea) for idea in ideas],
        query=query,
        genre_filter=genre_filter,
        emotion_filter=emotion_filter,
        duration_filter=duration_filter,
        complexity_filter=complexity_filter,
        sort=sort,
    )
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    page_payloads = filtered_payloads[safe_offset : safe_offset + safe_limit]
    return [idea_by_id[cast(UUID, payload["id"])] for payload in page_payloads], len(
        filtered_payloads
    )
