import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from app.config.settings import get_settings
from app.generation.prompt_language import ensure_portuguese_prompt_text
from app.storyboards.models import StoryboardFrame
from app.storytelling.models import Scene, Shot
from app.video_generation.retry import exponential_backoff_seconds

VIDEO_PROMPT_OVERRIDES_KEY = "video_prompt_overrides"


def _service_attr(name: str, fallback: object) -> Any:
    service = sys.modules.get("app.video_generation.service")
    return getattr(service, name, fallback) if service is not None else fallback


def video_idempotency_key(
    storyboard_frame_id: UUID,
    variant_index: int,
    provider: str,
    model: str,
    fingerprint: str = "",
) -> str:
    raw = f"{storyboard_frame_id}:{variant_index}:{provider}:{model}:{fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _video_request_fingerprint(
    frame: StoryboardFrame,
    source_image_uri: str | None,
    provider: str,
    model: str,
    aspect_ratio: str,
    size: str,
    video_prompt: str | None = None,
    reference_uris: list[str] | None = None,
) -> str:
    frame_metadata = frame.metadata_json if isinstance(frame.metadata_json, dict) else {}
    payload = {
        "storyboard_frame_id": str(frame.id),
        "storyboard_frame_fingerprint": frame_metadata.get("frame_fingerprint"),
        "source_image_asset_id": str(frame.asset_id),
        "source_image_uri": source_image_uri,
        "storyboard_prompt": frame.prompt,
        "video_prompt": video_prompt or frame.prompt,
        "reference_uris": list(reference_uris or []),
        "duration_seconds": frame.duration_seconds,
        "provider": provider,
        "model": model,
        "aspect_ratio": aspect_ratio,
        "size": size,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def _video_motion_prompt(
    frame: StoryboardFrame,
    shot: Shot | None = None,
    scene: Scene | None = None,
) -> str:
    scene_label = (
        f"Cena {scene.scene_number}" if scene is not None else f"Frame {frame.frame_number}"
    )
    shot_label = f"plano {shot.shot_number}" if shot is not None else "plano do storyboard"
    action = (
        str(getattr(shot, "action", "") or "").strip() or "animar a acao descrita no storyboard"
    )
    emotion = str(getattr(shot, "emotion", "") or "").strip() or "emocao coerente com o plano"
    camera_movement = (
        str(getattr(shot, "camera_movement", "") or "").strip()
        or "movimento suave e fisicamente plausivel"
    )
    composition = (
        str(getattr(shot, "visual_composition", "") or "").strip()
        or "preservar a composicao do primeiro frame"
    )
    dialogue = str(getattr(shot, "dialogue_text", "") or frame.dialogue_text or "").strip()
    audio_guidance = (
        "Diálogo dos personagens como referência de atuação, ritmo e leitura labial; "
        f"não gerar narracao, legendas visuais ou cartelas: {dialogue}."
        if dialogue
        else (
            "Cena sem fala neste plano; não criar narracao, legendas, cartelas ou palavras na cena."
        )
    )
    return (
        "Gere um clipe vertical 9:16 de video a partir de imagem, usando o primeiro "
        "frame fornecido.\n"
        f"Duracao obrigatoria: {frame.duration_seconds}s.\n"
        f"Origem narrativa: {scene_label}, {shot_label}.\n\n"
        "Use o primeiro frame como referência visual absoluta:\n"
        "- mantenha exatamente os mesmos personagens, rostos, idade aparente, figurino, "
        "objetos, luz, paleta, ambiente, escala e composicao de partida\n"
        "- não redesenhe personagens, não troque roupa, cabelo, cenario ou objeto\n"
        "- não adicione personagens, textos, logos, legendas, marcas d'agua, interface visual ou "
        "elementos que não aparecem no frame\n\n"
        f"Movimento narrativo do clipe: {action}.\n"
        f"Emocao dominante: {emotion}.\n"
        f"Movimento de camera: {camera_movement}.\n"
        f"Composicao de partida: {composition}.\n"
        f"{audio_guidance}\n\n"
        "Direcao temporal:\n"
        "- comece exatamente do primeiro frame fornecido\n"
        "- execute apenas uma acao principal clara durante o clipe\n"
        "- mantenha movimento natural, sutil e fisicamente plausivel\n"
        "- preserve continuidade espacial, proporções corporais e escala dos objetos\n"
        "- evite cortes, transicoes, zooms bruscos, flicker, warping, morphing, "
        "mudanca de identidade ou troca de roupa\n"
        "- termine em um estado visual coerente com a acao do plano\n\n"
        "Estilo: cinematográfico, realista, iluminação consistente, movimento suave, "
        "sem distorcao de rosto, mãos, olhos, boca ou objetos. O clipe deve parecer "
        "uma extensão natural do storyboard, não uma nova cena."
    )


def _video_prompt_override_map(metadata: dict) -> dict[str, str]:
    raw_store = metadata.get(VIDEO_PROMPT_OVERRIDES_KEY)
    if not isinstance(raw_store, dict):
        return {}
    return {
        str(frame_id): str(prompt)
        for frame_id, prompt in raw_store.items()
        if str(prompt or "").strip()
    }


def _video_prompt_override(metadata: dict, frame_id: UUID) -> str | None:
    return _video_prompt_override_map(metadata).get(str(frame_id))


def _video_effective_prompt(
    metadata: dict,
    frame: StoryboardFrame,
    shot: Shot | None = None,
    scene: Scene | None = None,
) -> str:
    return ensure_portuguese_prompt_text(
        _video_prompt_override(metadata, frame.id) or _video_motion_prompt(frame, shot, scene)
    )


def _store_video_prompt_override(metadata: dict, frame_id: UUID, prompt: str) -> dict:
    updated = dict(metadata or {})
    store = dict(_video_prompt_override_map(updated))
    store[str(frame_id)] = prompt.strip()
    updated[VIDEO_PROMPT_OVERRIDES_KEY] = store
    return updated


def _local_storage_path(storage_uri: str | None) -> Path | None:
    if not storage_uri:
        return None
    settings_factory = _service_attr("get_settings", get_settings)
    storage_root = settings_factory().local_storage_path.resolve()
    path = Path(storage_uri)
    try:
        candidate = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    try:
        candidate.relative_to(storage_root)
    except ValueError:
        return None
    return candidate


def _failed_job_payload(
    frame: StoryboardFrame,
    variant_index: int,
    reason: str,
    attempts: int,
) -> dict:
    return {
        "storyboard_frame_id": str(frame.id),
        "frame_number": frame.frame_number,
        "variant_index": variant_index,
        "reason": reason,
        "retry_after_seconds": exponential_backoff_seconds(attempts),
        "retry_available": "manual",
    }
