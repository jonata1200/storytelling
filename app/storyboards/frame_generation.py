import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from uuid import UUID

from app.providers.image.types import ImageGenerationRequest, ImageProvider, ImageResult
from app.storyboards.models import StoryboardFrame
from app.storytelling.models import Scene, Shot
from app.visual_bible.service import _generate_image_with_provider_fallback

DEFAULT_STORYBOARD_IMAGE_CONCURRENCY = 3
MAX_STORYBOARD_IMAGE_CONCURRENCY = 6
StoryboardProgressCallback = Callable[[int, int, str], Awaitable[None] | None]
logger = logging.getLogger(__name__)


def _deleted_progress_context_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "client this element belongs to has been deleted" in text
        or "parent element this slot belongs to has been deleted" in text
    )


async def _emit_storyboard_progress(
    callback: StoryboardProgressCallback | None,
    completed: int,
    total: int,
    detail: str,
) -> None:
    if callback is None:
        return
    try:
        result = callback(completed, total, detail)
        if inspect.isawaitable(result):
            await result
    except RuntimeError as exc:
        if not _deleted_progress_context_error(exc):
            raise
        logger.warning("Storyboard progress ignored because the page context was removed.")


@dataclass
class StoryboardFrameGenerationPlan:
    shot: Shot
    scene: Scene
    frame_number: int
    prompt: str
    existing_frame: StoryboardFrame | None
    needs_image: bool
    asset_artifact_id: UUID
    reference_uris: list[str] = field(default_factory=list)
    image: ImageResult | None = None
    fallback_metadata: dict | None = None
    duration_ms: int | None = None
    error: Exception | None = None


def _storyboard_progress_target(plan: StoryboardFrameGenerationPlan) -> str:
    scene_number = int(getattr(plan.scene, "scene_number", 0) or 0)
    shot_number = int(getattr(plan.shot, "shot_number", 0) or 0)
    return (
        f"Cena {scene_number:02d} - Plano {shot_number:02d} - "
        f"Quadro {plan.frame_number:03d}"
    )


def _storyboard_progress_detail(
    *,
    action: str,
    plan: StoryboardFrameGenerationPlan | None,
    completed: int,
    total: int,
    concurrency: int,
) -> str:
    pending = max(total - completed, 0)
    if plan is None:
        if total <= 0:
            return (
                "Agora: nenhum quadro novo precisa de imagem.\n"
                "Falta: salvar metadados e atualizar o animatic quando necessario."
            )
        return (
            f"Agora: preparando {total} quadro(s) para geracao.\n"
            f"Concluido: {completed}/{total}. Falta: {pending}.\n"
            f"Processamento: ate {concurrency} imagem(ns) em paralelo."
        )
    reference_count = len(plan.reference_uris)
    return (
        f"Agora: {action} {_storyboard_progress_target(plan)}.\n"
        f"Concluido: {completed}/{total}. Falta: {pending}.\n"
        f"Referencias visuais usadas: {reference_count}."
    )


def storyboard_image_concurrency(value: object) -> int:
    try:
        if value is None or value == 0:
            parsed = DEFAULT_STORYBOARD_IMAGE_CONCURRENCY
        elif isinstance(value, int):
            parsed = value
        elif isinstance(value, str):
            parsed = int(value)
        else:
            parsed = int(str(value))
    except (TypeError, ValueError):
        parsed = DEFAULT_STORYBOARD_IMAGE_CONCURRENCY
    return max(1, min(MAX_STORYBOARD_IMAGE_CONCURRENCY, parsed))


async def generate_storyboard_plan_images(
    provider: ImageProvider,
    plans: list[StoryboardFrameGenerationPlan],
    *,
    output_dir: Path,
    image_resolution: str | None,
    image_aspect_ratio: str,
    image_model: str,
    concurrency: int,
    progress_callback: StoryboardProgressCallback | None = None,
) -> None:
    safe_concurrency = storyboard_image_concurrency(concurrency)
    semaphore = asyncio.Semaphore(safe_concurrency)
    plans_to_generate = [plan for plan in plans if plan.needs_image and plan.image is None]
    total = len(plans_to_generate)
    completed = 0
    progress_lock = asyncio.Lock()
    stop_after_error = asyncio.Event()
    await _emit_storyboard_progress(
        progress_callback,
        0,
        total,
        _storyboard_progress_detail(
            action="preparando",
            plan=None,
            completed=0,
            total=total,
            concurrency=safe_concurrency,
        ),
    )

    async def generate_plan(plan: StoryboardFrameGenerationPlan) -> None:
        nonlocal completed
        if not plan.needs_image:
            return
        if stop_after_error.is_set():
            return
        try:
            async with semaphore:
                if stop_after_error.is_set():
                    return
                async with progress_lock:
                    await _emit_storyboard_progress(
                        progress_callback,
                        completed,
                        total,
                        _storyboard_progress_detail(
                            action="gerando",
                            plan=plan,
                            completed=completed,
                            total=total,
                            concurrency=safe_concurrency,
                        ),
                    )
                generation_started_at = perf_counter()
                image, fallback_metadata = await _generate_image_with_provider_fallback(
                    provider,
                    ImageGenerationRequest(
                        prompt=plan.prompt,
                        target_id=str(plan.shot.id),
                        view_type=f"storyboard_{plan.frame_number:03d}",
                        output_dir=output_dir,
                        aspect_ratio=image_aspect_ratio,
                        resolution=image_resolution,
                        negative_prompt=(
                            "animacao, desenho caricato, desenho, ilustracao, renderizacao 3D, "
                            "anime, quadrinhos, pintura, arte conceitual, personagem diferente, "
                            "rosto diferente, figurino diferente, cenario diferente, objeto "
                            "diferente, texto, legenda, marca d'agua, interface visual"
                        ),
                        references=plan.reference_uris,
                        model=image_model,
                    ),
                )
                plan.image = image
                plan.fallback_metadata = fallback_metadata
                plan.duration_ms = max(1, int((perf_counter() - generation_started_at) * 1000))
        except Exception as exc:
            plan.error = exc
            stop_after_error.set()
        finally:
            async with progress_lock:
                completed += 1
                await _emit_storyboard_progress(
                    progress_callback,
                    completed,
                    total,
                    _storyboard_progress_detail(
                        action="concluido" if completed < total else "finalizando",
                        plan=plan,
                        completed=completed,
                        total=total,
                        concurrency=safe_concurrency,
                    ),
                )

    await asyncio.gather(*(generate_plan(plan) for plan in plans_to_generate))
