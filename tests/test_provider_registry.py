from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

import app.providers.image.types as image_types
from app.config.provider_policy import (
    effective_provider_for_channel,
    provider_requires_api_key,
)
from app.config.settings import Settings
from app.generation.shot_generation_spec import ShotGenerationSpec
from app.providers.image.types import ImageGenerationRequest
from app.providers.registry import ProviderRegistry


class _Provider:
    provider_name = "test"


@pytest.mark.parametrize("channel", ["text", "image"])
def test_registry_resolves_each_channel(channel: str) -> None:
    registry = ProviderRegistry()
    registry.register(channel, "test", _Provider)  # type: ignore[arg-type]

    resolved: Any = registry.resolve(channel, "test")  # type: ignore[arg-type]
    assert resolved.provider_name == "test"


def test_registry_rejects_provider_without_registered_adapter() -> None:
    with pytest.raises(ValueError, match="não possui adapter registrado"):
        ProviderRegistry().resolve("image", "missing")


def test_provider_channels_accept_migration_targets() -> None:
    settings = Settings(
        _env_file=None,
        text_provider="ollama_cloud",
        image_provider="meta",
    )

    assert effective_provider_for_channel(settings, "text") == "ollama_cloud"
    assert effective_provider_for_channel(settings, "image") == "meta"


def test_api_mode_requires_key_and_browser_mode_does_not() -> None:
    api = Settings(_env_file=None, ollama_cloud_integration_mode="api")
    browser = Settings(_env_file=None, meta_image_integration_mode="browser")

    assert provider_requires_api_key(api, "ollama_cloud") is True
    assert provider_requires_api_key(browser, "meta") is False


def test_browser_profile_rejects_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="META_BROWSER_PROFILE_PATH"):
        Settings(_env_file=None, meta_browser_profile_path=Path("../outside"))


def test_image_output_rejects_path_outside_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = tmp_path / "storage"
    monkeypatch.setattr(
        image_types,
        "get_settings",
        lambda: SimpleNamespace(local_storage_path=storage),
    )

    with pytest.raises(ValueError, match="output_dir"):
        ImageGenerationRequest(
            prompt="A quiet street",
            model="model",
            output_dir=tmp_path / "outside",
        )


def test_shot_generation_spec_serializes_without_provider_names() -> None:
    spec = ShotGenerationSpec(
        shot_id=uuid4(),
        scene_id=uuid4(),
        scene_title="Praça",
        scene_summary="Ana atravessa a praça",
        duration_seconds=4.5,
        characters=["Ana"],
        location="Praça",
        props=["guarda-chuva"],
        action="caminha",
        emotion="esperança",
        camera="travelling lateral",
        visual_composition="plano médio lateral",
        lighting="amanhecer",
        continuity={"wardrobe": "casaco azul"},
        visual_references=["storage/generated_images/ana.png"],
        previous_frame_reference="storage/generated_videos/frame.jpg",
    )

    payload = spec.model_dump(mode="json")
    assert payload["duration_seconds"] == 4.5
    assert "provider" not in payload
    assert "meta" not in str(payload).casefold()
    assert "vibes" not in str(payload).casefold()
