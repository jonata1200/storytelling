from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

import app.visual_bible.image_generation as generation
from app.assets.models import Asset, AssetVersion
from app.config.settings import Settings
from app.costs.models import CostEntry
from app.projects.models import Artifact
from app.providers.image.types import ImageGenerationResult
from app.visual_bible.image_generation import (
    enqueue_visual_reference_generation,
    generate_visual_reference,
    prepare_vibes_ingredient_metadata,
    sanitize_meta_image_prompt,
    validate_identity_prompt,
    visual_reference_aspect_ratio,
    visual_reference_generation_issue,
)
from app.visual_bible.models import Character, VisualReference
from app.visual_bible.reference_planning import CHARACTER_META_INSTRUCTION, plan_visual_references


class _ImageProvider:
    provider_name = "meta"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.prompts: list[str] = []

    async def generate(self, request: Any) -> ImageGenerationResult:
        self.prompts.append(request.prompt)
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

    async def execute(self, _statement: Any) -> Any:
        references = [
            item
            for item in self.added
            if isinstance(item, VisualReference) and item.status != "rejected"
        ]
        return SimpleNamespace(scalars=lambda: references)

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


def test_visual_reference_aspect_ratio_depends_on_target_kind() -> None:
    assert visual_reference_aspect_ratio("character") == "9:16"
    assert visual_reference_aspect_ratio("location") == "9:16"


def test_sanitize_meta_image_prompt_rewrites_refusal_triggers() -> None:
    # O caso real: "Cicatriz em forma de 'V' no pescoço (marca de faca)".
    sanitized = sanitize_meta_image_prompt(
        "Crie a imagem de Leonardo, com cicatriz em forma de 'V' no pescoço "
        "(marca de faca), deve ter olhos azul-acinzentados."
    )
    assert "marca de faca" not in sanitized.casefold()
    assert "cicatriz" in sanitized.casefold()
    assert "leonardo" in sanitized.casefold()

    # Tudo é canonicalizado para "cicatriz de faca"/"cicatriz" (sem armas visíveis).
    assert "cicatriz de faca" in sanitize_meta_image_prompt("com marcas de facadas no braço")
    assert "cicatriz" in sanitize_meta_image_prompt("com ferida aberta no lábio")
    assert "cicatriz" in sanitize_meta_image_prompt("com cortes profundos no antebraço")
    assert "machucado" in sanitize_meta_image_prompt("rosto ensanguentado")
    assert "hematomas" in sanitize_meta_image_prompt("com sangue no canto da boca")
    # "sem sangue" é instrução de segurança — não deve ser reescrito.
    assert "sem sangue" in sanitize_meta_image_prompt("sem sangue, sem cortes")


def test_sanitize_meta_image_prompt_keeps_clean_prompt_untouched() -> None:
    prompt = (
        "Crie a imagem de Ana, deve ter cabelo preto, olhos castanhos, "
        "deve usar casaco azul."
    )
    assert sanitize_meta_image_prompt(prompt) == prompt


def test_visual_reference_generation_reports_disabled_browser_automation() -> None:
    settings = Settings(
        _env_file=None,
        meta_image_model="muse-image",
        meta_browser_automation_enabled=False,
    )

    assert "automação de imagens nos Ajustes" in visual_reference_generation_issue(settings)

    settings.meta_browser_automation_enabled = True
    assert visual_reference_generation_issue(settings, browser_backend_available=True) == ""


@pytest.mark.asyncio
async def test_enqueue_rejects_unavailable_image_provider_before_creating_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        meta_image_model="muse-image",
        meta_browser_automation_enabled=False,
    )
    create_called = False

    async def fake_create(*_args: Any, **_kwargs: Any) -> None:
        nonlocal create_called
        create_called = True

    monkeypatch.setattr(generation, "get_settings", lambda: settings)
    monkeypatch.setattr(generation, "create_or_get_media_job", fake_create)

    with pytest.raises(RuntimeError, match="automação de imagens nos Ajustes"):
        await enqueue_visual_reference_generation(
            cast(Any, _Session.__new__(_Session)), uuid4(), "character", uuid4(), "front"
        )

    async def execute(self, _statement: Any) -> Any:  # type: ignore[no-untyped-def]
        references = [
            item
            for item in self.added
            if isinstance(item, VisualReference) and item.status != "rejected"
        ]
        return SimpleNamespace(scalars=lambda: references)

    assert create_called is False


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
    assert [item.view_type for item in plan.items] == ["full_body"]
    assert "de corpo inteiro" in plan.items[0].prompt
    assert "9:16" in plan.items[0].prompt
    assert plan.items[0].prompt.endswith(CHARACTER_META_INSTRUCTION)
    assert "Não inclua textos, letras, legendas, logotipos" in plan.items[0].prompt

    location = plan_visual_references(
        "location",
        uuid4(),
        {"canonical_prompt": "Sala antiga.", "lighting": "luz noturna"},
        shot_payloads=[{"camera": "contracampo reverso"}],
    )
    assert [item.view_type for item in location.items] == ["establishing"]
    assert "ambiente inteiro em plano geral" in location.items[0].prompt
    assert "sem pessoas" in location.items[0].prompt
    assert "fundo simples" not in location.items[0].prompt


@pytest.mark.asyncio
async def test_prompt_override_is_sent_without_duplicating_canonical_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_id = uuid4()
    character = Character(
        id=uuid4(),
        project_id=project_id,
        artifact_id=uuid4(),
        name="Ana",
        role="protagonista",
        canonical_profile={"canonical_prompt": "Prompt canônico antigo."},
        character_fingerprint={"sha256": "fingerprint"},
    )
    session = _Session(character)
    settings = Settings(_env_file=None, local_storage_path=tmp_path)
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
    edited_prompt = "Prompt revisado pelo usuário, corpo inteiro e fundo simples."

    await generate_visual_reference(
        cast(Any, session),
        project_id,
        "character",
        character.id,
        "full_body",
        prompt_override=edited_prompt,
        provider=provider,
    )

    assert len(provider.prompts) == 1
    assert provider.prompts[0].startswith(edited_prompt)
    assert provider.prompts[0] == f"{edited_prompt} {CHARACTER_META_INSTRUCTION}"


@pytest.mark.asyncio
async def test_character_prompt_with_refusal_trigger_is_sanitized_for_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_id = uuid4()
    character = Character(
        id=uuid4(),
        project_id=project_id,
        artifact_id=uuid4(),
        name="Leonardo",
        role="protagonista",
        canonical_profile={
            "canonical_prompt": (
                "Crie a imagem de Leonardo, com cicatriz em forma de 'V' no pescoço "
                "(marca de faca), deve ter 1,78 m de altura."
            )
        },
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

    reference = await generate_visual_reference(
        cast(Any, session), project_id, "character", character.id, "full_body", provider=provider
    )

    assert len(provider.prompts) == 1
    # O prompt ENVIADO ao provedor não contém o gatilho de recusa...
    assert "marca de faca" not in provider.prompts[0].casefold()
    assert "cicatriz em forma de 'v'" in provider.prompts[0].casefold()
    # ...mas o texto SALVO na referência preserva o perfil canônico integral.
    assert "marca de faca" in str(reference.prompt).casefold()


@pytest.mark.asyncio
async def test_character_regeneration_supersedes_prior_reference_and_keeps_history(
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
        cast(Any, session), project_id, "character", character.id, "front", provider=provider
    )
    second = await generate_visual_reference(
        cast(Any, session), project_id, "character", character.id, "front", provider=provider
    )

    assets = [item for item in session.added if isinstance(item, Asset)]
    versions = [item for item in session.added if isinstance(item, AssetVersion)]
    costs = [item for item in session.added if isinstance(item, CostEntry)]
    assert first.id != second.id
    assert first.asset_id != second.asset_id
    assert first.status == "rejected"
    assert first.metadata_json["superseded"] is True
    assert second.status == "approved"
    assert second.is_canonical is True
    assert second.metadata_json["approved"] is True
    assert second.metadata_json["canonical"] is True
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
