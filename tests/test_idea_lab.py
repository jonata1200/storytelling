from pathlib import Path

import pytest

from app.config.settings import Settings
from app.storytelling import idea_lab
from app.storytelling.idea_lab import (
    delete_saved_idea,
    generate_freeform_ideas,
    load_saved_ideas,
    save_idea,
)


@pytest.mark.asyncio
async def test_generate_freeform_ideas_returns_ten_ai_suggested_ideas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(idea_lab, "get_settings", lambda: Settings(openrouter_api_key=None))
    ideas = await generate_freeform_ideas("uma memoria de infancia", count=10)

    assert len(ideas) == 10
    assert all(idea.get("genre") for idea in ideas)
    assert all(idea.get("primary_emotion") for idea in ideas)


def test_saved_ideas_can_be_saved_and_deleted(tmp_path: Path) -> None:
    path = tmp_path / "saved-ideas.json"
    saved = save_idea(
        {
            "id": "idea-1",
            "title": "A chave no jardim",
            "genre": "Suspense",
            "primary_emotion": "Curiosidade",
        },
        path,
    )

    assert saved["id"] == "idea-1"
    assert load_saved_ideas(path)[0]["title"] == "A chave no jardim"

    delete_saved_idea("idea-1", path)

    assert load_saved_ideas(path) == []
