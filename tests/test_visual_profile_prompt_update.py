from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.projects.models import Artifact
from app.visual_bible import service as visual_service
from app.visual_bible.models import Character, Location


class _Session:
    def __init__(self, target: Any, artifact: Artifact | None) -> None:
        self.target = target
        self.artifact = artifact
        self.committed = False
        self.refreshed = False

    async def get(self, model: type[Any], identity: Any, **_kwargs: Any) -> Any:
        if model is Artifact and self.artifact is not None:
            return self.artifact
        if (model is Character or model is Location) and identity == self.target.id:
            return self.target
        return None

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _obj: Any) -> None:
        self.refreshed = True


@pytest.mark.asyncio
async def test_update_visual_profile_prompt_saves_character_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    character = Character(
        id=uuid4(),
        project_id=project_id,
        artifact_id=uuid4(),
        name="Ana",
        role="protagonista",
        canonical_profile={"canonical_prompt": "Prompt antigo."},
        character_fingerprint={"sha256": "x"},
    )
    artifact = Artifact(
        id=character.artifact_id,
        project_id=project_id,
        artifact_type="CHARACTER",
        name="Ana",
        status="READY_FOR_REVIEW",
    )
    session = _Session(character, artifact)

    async def fake_create_artifact_version(
        _session: Any, _artifact: Any, payload: dict, change_note: str | None = None
    ) -> Any:
        assert payload["canonical_prompt"] == "Prompt novo editado."
        assert change_note == "Canonical prompt edited by user"
        return SimpleNamespace()

    monkeypatch.setattr(
        "app.projects.versioning.create_artifact_version", fake_create_artifact_version
    )

    result = await visual_service.update_visual_profile_prompt(
        session,  # type: ignore[arg-type]
        project_id,
        "character",
        character.id,
        "Prompt novo editado.",
    )

    assert result is character
    assert character.canonical_profile["canonical_prompt"] == "Prompt novo editado."
    assert session.committed is True


@pytest.mark.asyncio
async def test_update_visual_profile_prompt_rejects_empty() -> None:
    project_id = uuid4()
    character = Character(
        id=uuid4(),
        project_id=project_id,
        artifact_id=uuid4(),
        name="Ana",
        role="protagonista",
        canonical_profile={"canonical_prompt": "Prompt antigo."},
        character_fingerprint={"sha256": "x"},
    )
    session = _Session(character, None)

    with pytest.raises(ValueError, match="não pode ficar vazio"):
        await visual_service.update_visual_profile_prompt(
            session,  # type: ignore[arg-type]
            project_id,
            "character",
            character.id,
            "   ",
        )
