from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

import app.visual_bible.image_generation as generation
from app.assets.models import Asset, AssetVersion
from app.config.settings import Settings
from app.costs.models import CostEntry
from app.projects.models import Artifact
from app.providers.image.types import ImageGenerationResult
from app.visual_bible.image_generation import (
    generate_visual_reference,
    prepare_vibes_ingredient_metadata,
    validate_identity_prompt,
)
from app.visual_bible.models import Character, VisualReference
from app.visual_bible.reference_planning import plan_visual_references


class _ImageProvider:
    provider_name = "meta"

    def __init__(self, root: Path) -> None:
        self.root = root

    async def generate(self, request: Any) -> ImageGenerationResult:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        path = request.output_dir / f"{uuid4().hex}.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
        return ImageGenerationResult(
            file_path=path,
            storage_uri=path.as_posix(),
            sha256="a" * 64,
            content_type="image/png",
            provider="meta",
            model="muse-image",
            prompt=request.prompt,
            external_job_id="meta-generation",
            metadata={"seed": 7},
        )


class _Session:
    def __init__(self, character: Character) -> None:
        self.character = character
        self.added: list[Any] = []

    async def get(self, model: type[Any], identity: Any, **_kwargs: Any) -> Any:
        if model is Character and identity == self.character.id:
            return self.character
        return next(
            (item for item in self.added if isinstance(item, model) and item.id == identity),
            None,
        )

    def add(self, item: Any) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid4()

    async def commit(self) -> None:
        return None

    async def refresh(self, _item: Any) -> None:
        return None


def test_reference_plan_is_bounded_and_uses_shot_needs() -> None:
    plan = plan_visual_references(
        "character",
        uuid4(),
        {
            "canonical_prompt": "Ana, cabelo preto, 35 anos, casaco azul.",
            "role": "protagonista",
            "base_outfit": "casaco azul",
        },
    )
    assert [item.view_type for item in plan.items] == [
        "front",
        "three_quarter",
        "profile",
        "full_body",
        "neutral_expression",
        "story_outfit",
    ]
    assert len(plan.items) == 6

    location = plan_visual_references(
        "location",
        uuid4(),
        {"canonical_prompt": "Sala antiga.", "lighting": "luz noturna"},
        shot_payloads=[{"camera": "contracampo reverso"}],
    )
    assert {item.view_type for item in location.items} == {
        "establishing",
        "main_angle",
        "reverse_angle",
        "story_lighting",
    }


@pytest.mark.asyncio
async def test_generation_persists_asset_version_and_keeps_regeneration_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_id = uuid4()
    character = Character(
        id=uuid4(),
        project_id=project_id,
        artifact_id=uuid4(),
        name="Ana",
        role="protagonista",
        canonical_profile={"canonical_prompt": "Ana, cabelo preto e casaco azul."},
        character_fingerprint={"sha256": "fingerprint"},
    )
    session = _Session(character)
    settings = Settings(
        _env_file=None,
        local_storage_path=tmp_path,
        image_provider="meta",
        meta_image_model="muse-image",
    )
    monkeypatch.setattr(generation, "get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.providers.image.types.get_settings",
        lambda: SimpleNamespace(local_storage_path=tmp_path),
    )
    monkeypatch.setattr(generation, "approved_visual_references", _empty_approved)

    async def fake_artifact(*_args: Any, **_kwargs: Any) -> Artifact:
        artifact = Artifact(
            id=uuid4(),
            project_id=project_id,
            artifact_type="VISUAL_REFERENCE",
            name="reference",
            status="READY_FOR_REVIEW",
        )
        session.add(artifact)
        return artifact

    monkeypatch.setattr(generation, "_create_artifact", fake_artifact)
    monkeypatch.setattr(generation, "_add_dependency", _noop_dependency)
    provider = _ImageProvider(tmp_path)

    first = await generate_visual_reference(
        session, project_id, "character", character.id, "front", provider=provider
    )
    second = await generate_visual_reference(
        session, project_id, "character", character.id, "front", provider=provider
    )

    assets = [item for item in session.added if isinstance(item, Asset)]
    versions = [item for item in session.added if isinstance(item, AssetVersion)]
    costs = [item for item in session.added if isinstance(item, CostEntry)]
    assert first.id != second.id
    assert first.asset_id != second.asset_id
    assert len(assets) == len(versions) == len(costs) == 2
    assert first.metadata_json["vibes"]["sync_status"] == "not_synced"
    assert first.metadata_json["provider_job_id"] == "meta-generation"


def test_identity_guardrail_and_vibes_sync_are_safe_and_idempotent() -> None:
    with pytest.raises(ValueError, match="características permanentes"):
        validate_identity_prompt("mudar cabelo e trocar a idade")

    reference = VisualReference(
        project_id=uuid4(),
        artifact_id=uuid4(),
        asset_id=uuid4(),
        target_kind="character",
        target_id=uuid4(),
        view_type="front",
        prompt="canonical",
        provider="meta",
        model="muse-image",
        status="approved",
        metadata_json={},
    )
    assert prepare_vibes_ingredient_metadata(
        reference, ingredient_id="ingredient-1", ingredient_type="character"
    )
    assert not prepare_vibes_ingredient_metadata(
        reference, ingredient_id="ingredient-1", ingredient_type="character"
    )


async def _empty_approved(*_args: Any, **_kwargs: Any) -> list[Any]:
    return []


async def _noop_dependency(*_args: Any, **_kwargs: Any) -> None:
    return None
