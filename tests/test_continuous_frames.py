from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

import app.video_generation.continuous_frames as continuous_frames
from app.providers.image.types import ImageGenerationRequest


@pytest.mark.asyncio
async def test_storyboard_frame_uses_supported_image_output(monkeypatch: Any) -> None:
    project_id = uuid4()
    storage_root = continuous_frames.get_settings().local_storage_path
    segment = SimpleNamespace(
        id=uuid4(),
        shot_id=None,
        prompt="A personagem observa o painel.",
        metadata_json={},
    )
    captured_requests: list[ImageGenerationRequest] = []

    class GenerationReachedProvider:
        async def generate(self, request: ImageGenerationRequest) -> object:
            captured_requests.append(request)
            raise RuntimeError("generation reached")

    async def no_references(*_args: object) -> list[object]:
        return []

    monkeypatch.setattr(
        continuous_frames,
        "get_settings",
        lambda: SimpleNamespace(local_storage_path=storage_root),
    )
    monkeypatch.setattr(
        continuous_frames,
        "effective_provider_for_channel",
        lambda *_args: "fake-image-provider",
    )
    monkeypatch.setattr(continuous_frames, "provider_model", lambda *_args: "fake-model")
    monkeypatch.setattr(
        continuous_frames,
        "resolve_image_provider",
        lambda *_args: GenerationReachedProvider(),
    )
    monkeypatch.setattr(continuous_frames, "_approved_references", no_references)

    with pytest.raises(RuntimeError, match="generation reached"):
        await continuous_frames._generate_frame(object(), project_id, segment, "initial")  # type: ignore[arg-type]

    assert len(captured_requests) == 1
    assert captured_requests[0].output_dir == storage_root / "generated_images" / str(project_id)


def test_storyboard_prompts_are_human_and_descriptive() -> None:
    segment = SimpleNamespace(
        prompt="A personagem atravessa a sala e desliga o painel.",
        metadata_json={
            "characters": ["Clara"],
            "locations": ["Bunker"],
            "shot_generation_spec": {
                "visual_composition": "Clara em primeiro plano diante do painel",
                "lighting": "luz azul suave vinda do painel",
                "emotion": "tensão silenciosa",
                "props": ["painel de controle", "chave metálica"],
                "character_states": {"Clara": {"outfit": "macacão cinza"}},
            },
        },
    )

    prompts = continuous_frames.segment_frame_prompts(segment)  # type: ignore[arg-type]

    assert prompts["initial"].startswith("Crie uma imagem de ")
    assert prompts["final"].startswith("Crie uma imagem.")
    # v3 dos frames (decisão do usuário): APENAS a ação, com os personagens
    # pelo nome. Sem contexto de cena, sem iluminação, figurino, props ou
    # "Mostre o momento inicial em que" — a identidade vem das referências
    # do chat onde todas as imagens são geradas.
    assert "atravessa a sala" in prompts["initial"]
    assert "Mostre o momento inicial" not in prompts["initial"]
    assert "A cena se passa" not in prompts["initial"]
    assert "A cena acontece" not in prompts["initial"]
    assert "Iluminação" not in prompts["initial"]
    assert "Iluminação" not in prompts["final"]
    assert "Os personagens devem aparecer assim" not in prompts["initial"]
    assert "Deixe visíveis os objetos importantes" not in prompts["initial"]
    assert "enquadramento" not in prompts["initial"].casefold()
    assert "progressão dramática" not in prompts["initial"].casefold()
    assert "9:16" not in prompts["initial"]
    assert "9:16" not in prompts["final"]
    # v2 dos frames: identidade por citação das imagens anteriores (a Meta
    # recusava "rosto ... exatamente ... referências"); frame final descreve a
    # pose da ação e trava a iluminação ao frame inicial.
    assert "rosto" not in prompts["initial"].casefold()
    assert "Use as mesmas imagens anteriores" not in prompts["initial"]
    assert "pose final da ação" in prompts["final"]
    assert "logo depois dessa ação" not in prompts["final"]
    # v3: a trava de iluminação do frame final foi removida — o próprio
    # chat/referências mantêm a luz consistente entre os frames.
    assert "mesma iluminação" not in prompts["final"]
    assert "Preserve rigorosamente" not in prompts["initial"]
    assert "movimento borrado" not in prompts["initial"]
    assert len(prompts["initial"]) <= continuous_frames.FRAME_PROMPT_MAX_CHARS
    assert len(prompts["final"]) < 350

    provider_prompt = continuous_frames.frame_provider_prompt(prompts["initial"], "initial")
    assert "fotorrealista" in provider_prompt
    assert "texto ou logos" in provider_prompt
    assert "identidades" not in provider_prompt
    assert "movimento borrado" not in provider_prompt


def test_storyboard_prompt_caps_oversized_generation_context() -> None:
    segment = SimpleNamespace(
        prompt="A personagem abre a porta.",
        metadata_json={
            "characters": ["Clara", "Caio", "Lia", "Beto", "Outro personagem"],
            "locations": ["Oficina subterrânea", "corredor", "praça"],
            "shot_generation_spec": {
                "action": "Clara abre a porta e encontra o motor. " * 30,
                "visual_composition": "plano detalhado com muitos elementos " * 30,
                "lighting": "luz azul lateral " * 30,
                "emotion": "tensão silenciosa " * 30,
                "props": ["motor antigo " * 20, "chave", "painel", "ferramenta"],
                "character_states": {
                    "Clara": {"outfit": "macacão cinza " * 20},
                    "Caio": {"outfit": "jaqueta azul " * 20},
                },
            },
        },
    )

    prompt = continuous_frames.segment_frame_prompts(segment)["initial"]  # type: ignore[arg-type]
    provider_prompt = continuous_frames.frame_provider_prompt(prompt, "initial")

    assert len(prompt) <= continuous_frames.FRAME_PROMPT_MAX_CHARS
    assert len(provider_prompt) < 750
    assert "Clara abre a porta" in prompt


def test_storyboard_prompt_deduplicates_locations_and_ignores_narrative_states() -> None:
    segment = SimpleNamespace(
        prompt="fallback",
        metadata_json={
            "characters": ["Elias", "Leo"],
            "locations": ["Auditório da Filarmônica", "AUDITÓRIO DA FILARMÔNICA"],
            "shot_generation_spec": {
                "action": "Um cronômetro digital vermelho neon marca 00:59 segundos.",
                "character_states": {
                    "Leo": {
                        "condition": (
                            "Ele apenas aponta para o chão de madeira do palco, "
                            "ordenando que Leo sinta a base."
                        ),
                        "continuity_notes": "Uma longa recapitulação narrativa da cena.",
                    }
                },
            },
        },
    )

    prompt = continuous_frames.segment_frame_prompts(segment)["initial"]  # type: ignore[arg-type]

    # v3: sem linha de contexto, nenhum dado de local entra no prompt —
    # nem em duplicidade. Estados narrativos (continuity_notes) ficam fora.
    assert "Auditório da Filarmônica" not in prompt
    assert "AUDITÓRIO DA FILARMÔNICA" not in prompt
    assert "A cena acontece" not in prompt
    assert "Ele apenas aponta" not in prompt
    assert "Os personagens devem aparecer assim" not in prompt
    assert "…" not in prompt


def test_storyboard_prompt_prioritizes_exact_shot_action_over_scene_summary() -> None:
    segment = SimpleNamespace(
        prompt="Resumo divergente: a cidade já está destruída.",
        metadata_json={
            "action": "Resumo divergente: a cidade já está destruída.",
            "source_text": "A cidade já está destruída. Ana procura abrigo.",
            "shot_generation_spec": {"action": "Ana abre a porta da oficina pela primeira vez"},
        },
    )

    prompts = continuous_frames.segment_frame_prompts(segment)  # type: ignore[arg-type]

    assert "Ana abre a porta da oficina pela primeira vez" in prompts["initial"]
    assert "cidade já está destruída" not in prompts["initial"]


def test_storyboard_prompt_removes_screenplay_markers_but_keeps_the_action() -> None:
    segment = SimpleNamespace(
        prompt="fallback",
        metadata_json={
            "storyboard_action": (
                "INT. OFICINA - DIA Ana ergue a porta metálica e encontra o motor desmontado."
            )
        },
    )

    prompts = continuous_frames.segment_frame_prompts(segment)  # type: ignore[arg-type]

    assert "INT." not in prompts["initial"]
    assert "Ana ergue a porta metálica" in prompts["initial"]


def test_storyboard_frames_use_first_and_last_script_beats_in_order() -> None:
    segment = SimpleNamespace(
        prompt="fallback",
        metadata_json={
            "storyboard_action": (
                "Ana entra na oficina. Ela acende a luz. Um ruído vem do armário. "
                "Ana abre o armário e encontra a carta escondida."
            )
        },
    )

    prompts = continuous_frames.segment_frame_prompts(segment)  # type: ignore[arg-type]

    assert "Ana entra na oficina" in prompts["initial"]
    assert "encontra a carta" not in prompts["initial"]
    assert "Ana abre o armário e encontra a carta" in prompts["final"]
    assert "Ana entra na oficina" not in prompts["final"]


def test_storyboard_excerpt_does_not_leave_a_dangling_article() -> None:
    excerpt = continuous_frames._clean_excerpt(
        "Plano detalhe das mãos na válvula. "
        "A respiração fica pesada enquanto a câmera recua e revela o personagem.",
        limit=42,
    )

    assert excerpt.endswith("…")
    assert not excerpt.endswith((" A…", " O…", " E…"))


@pytest.mark.asyncio
async def test_final_frame_uses_inherited_initial_frame_as_first_reference(
    monkeypatch: Any,
) -> None:
    source_asset_id = uuid4()
    source_asset = SimpleNamespace(
        id=source_asset_id,
        storage_uri="storage/generated_images/previous-final.png",
    )
    segment = SimpleNamespace(source_frame_asset_id=source_asset_id)

    class FakeSession:
        async def get(self, _model: object, asset_id: object) -> object:
            assert asset_id == source_asset_id
            return source_asset

    async def canonical_references(*_args: object) -> list[object]:
        return []

    monkeypatch.setattr(continuous_frames, "_approved_references", canonical_references)

    references = await continuous_frames._storyboard_frame_references(
        FakeSession(), uuid4(), segment  # type: ignore[arg-type]
    )

    assert len(references) == 1
    assert references[0].role == "initial_frame"
    assert references[0].uri == source_asset.storage_uri


def test_approval_propagates_final_frame_and_invalidates_stale_chain() -> None:
    approved_final_id = uuid4()
    segment = SimpleNamespace(
        id=uuid4(),
        final_frame_asset_id=approved_final_id,
        metadata_json={"final_frame_storage_uri": "storage/new-final.png"},
    )
    next_segment = SimpleNamespace(
        id=uuid4(),
        source_segment_id=uuid4(),
        source_frame_asset_id=uuid4(),
        final_frame_asset_id=uuid4(),
        metadata_json={"storyboard_approved": True, "final_frame_asset_id": str(uuid4())},
    )
    later_segment = SimpleNamespace(
        id=uuid4(),
        source_segment_id=next_segment.id,
        source_frame_asset_id=next_segment.final_frame_asset_id,
        final_frame_asset_id=uuid4(),
        metadata_json={"storyboard_approved": True, "initial_frame_asset_id": str(uuid4())},
    )

    continuous_frames.propagate_approved_storyboard_frame(
        segment,  # type: ignore[arg-type]
        [next_segment, later_segment],  # type: ignore[list-item]
    )

    assert next_segment.source_segment_id == segment.id
    assert next_segment.source_frame_asset_id == approved_final_id
    assert next_segment.final_frame_asset_id is None
    assert next_segment.metadata_json["initial_frame_asset_id"] == str(approved_final_id)
    assert next_segment.metadata_json["storyboard_approved"] is False
    assert later_segment.source_frame_asset_id is None
    assert later_segment.final_frame_asset_id is None
    assert later_segment.metadata_json["storyboard_approved"] is False
