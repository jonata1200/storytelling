from uuid import uuid4

from app.providers.video.mock import MockVideoProvider
from app.storyboards.models import StoryboardFrame
from app.storytelling.models import Scene, Shot
from app.video_generation.planning import (
    _store_video_prompt_override,
    _video_effective_prompt,
    _video_motion_prompt,
    _video_request_fingerprint,
    video_generation_validation_errors,
    video_idempotency_key,
)
from app.video_generation.retry import exponential_backoff_seconds


def test_exponential_backoff_caps_delay() -> None:
    assert exponential_backoff_seconds(1, base_seconds=2, cap_seconds=10) == 2
    assert exponential_backoff_seconds(3, base_seconds=2, cap_seconds=10) == 8
    assert exponential_backoff_seconds(10, base_seconds=2, cap_seconds=10) == 10


def test_video_idempotency_key_changes_when_frame_fingerprint_changes() -> None:
    frame = StoryboardFrame(
        id=uuid4(),
        asset_id=uuid4(),
        duration_seconds=5,
        prompt="Prompt de storyboard completo para video vertical.",
        metadata_json={"frame_fingerprint": "frame-a"},
    )

    first_fingerprint = _video_request_fingerprint(
        frame,
        "asset://frame-a",
        "mock",
        "mock-video",
        "9:16",
        "1080x1920",
    )
    frame.metadata_json = {"frame_fingerprint": "frame-b"}
    second_fingerprint = _video_request_fingerprint(
        frame,
        "asset://frame-a",
        "mock",
        "mock-video",
        "9:16",
        "1080x1920",
    )

    assert first_fingerprint != second_fingerprint
    assert video_idempotency_key(
        frame.id, 1, "mock", "mock-video", first_fingerprint
    ) != video_idempotency_key(frame.id, 1, "mock", "mock-video", second_fingerprint)


def test_video_effective_prompt_uses_saved_frame_override() -> None:
    frame = StoryboardFrame(
        id=uuid4(),
        shot_id=uuid4(),
        asset_id=uuid4(),
        frame_number=1,
        duration_seconds=5,
        prompt="Prompt de storyboard completo para video vertical.",
    )
    metadata = _store_video_prompt_override({}, frame.id, "Mover lentamente a camera.")

    assert _video_effective_prompt(metadata, frame) == "Mover lentamente a camera."


def test_video_fingerprint_changes_when_video_prompt_changes() -> None:
    frame = StoryboardFrame(
        id=uuid4(),
        asset_id=uuid4(),
        duration_seconds=5,
        prompt="Prompt de storyboard completo para video vertical.",
        metadata_json={"frame_fingerprint": "frame-a"},
    )

    first_fingerprint = _video_request_fingerprint(
        frame,
        "asset://frame-a",
        "mock",
        "mock-video",
        "9:16",
        "1080x1920",
        "Movimento suave.",
    )
    second_fingerprint = _video_request_fingerprint(
        frame,
        "asset://frame-a",
        "mock",
        "mock-video",
        "9:16",
        "1080x1920",
        "Movimento rapido.",
    )

    assert first_fingerprint != second_fingerprint


def test_video_motion_prompt_guides_image_to_video_continuity() -> None:
    frame = StoryboardFrame(
        id=uuid4(),
        shot_id=uuid4(),
        asset_id=uuid4(),
        frame_number=3,
        duration_seconds=6,
        prompt="Storyboard frame cinematografico para video vertical 9:16.",
        narration_text="Clara abre a carta.",
        dialogue_text="",
    )
    scene = Scene(id=uuid4(), scene_number=2, title="A carta")
    shot = Shot(
        id=frame.shot_id,
        shot_number=4,
        duration_seconds=6,
        action="Clara abre a carta azul diante da janela.",
        emotion="revelacao silenciosa",
        visual_composition="Clara em primeiro plano, janela ao fundo.",
        camera_movement="push-in lento",
        narration_text="Clara abre a carta.",
        dialogue_text="",
    )

    prompt = _video_motion_prompt(frame, shot, scene)

    assert "Gere um clipe image-to-video vertical 9:16" in prompt
    assert "Duracao obrigatoria: 6s" in prompt
    assert "Cena 2, plano 4" in prompt
    assert "primeiro frame como referencia visual absoluta" in prompt
    assert "Clara abre a carta azul diante da janela" in prompt
    assert "push-in lento" in prompt
    assert "evite cortes, transicoes, zooms bruscos" in prompt
    assert "sem distorcao de rosto, maos, olhos, boca ou objetos" in prompt


def test_video_generation_validation_reports_bad_frame_inputs() -> None:
    frame = StoryboardFrame(
        id=uuid4(),
        asset_id=None,
        duration_seconds=99,
        prompt="curto",
    )

    errors = video_generation_validation_errors(
        frame,
        None,
        MockVideoProvider(),
        "16:9",
    )

    assert "frame sem asset_id" in errors
    assert "prompt generico demais" in errors
    assert "imagem fonte ausente" in errors
    assert "duracao 99s nao suportada pelo provider" in errors
    assert "aspect_ratio 16:9 nao suportado pelo provider" in errors


def test_video_generation_validation_uses_effective_video_prompt() -> None:
    frame = StoryboardFrame(
        id=uuid4(),
        asset_id=uuid4(),
        duration_seconds=5,
        prompt="curto",
    )

    errors = video_generation_validation_errors(
        frame,
        "asset://frame-a",
        MockVideoProvider(),
        "9:16",
        "Prompt de video suficientemente detalhado para animar este plano cinematografico.",
    )

    assert "prompt generico demais" not in errors
