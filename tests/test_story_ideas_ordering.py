from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.storytelling.story_ideas import list_story_ideas


class _FakeStoryIdeasSession:
    def __init__(self) -> None:
        self.executed_sql = ""

    async def get(self, model: type, identifier: object) -> SimpleNamespace:
        _ = model, identifier
        return SimpleNamespace(deleted_at=None)

    async def execute(self, statement: Any) -> Any:
        self.executed_sql = str(statement)
        return SimpleNamespace(scalars=lambda: [])


@pytest.mark.asyncio
async def test_list_story_ideas_orders_newest_first() -> None:
    session = _FakeStoryIdeasSession()

    ideas = await list_story_ideas(cast(AsyncSession, session), uuid4())

    assert ideas == []
    assert "story_ideas.created_at DESC" in session.executed_sql
