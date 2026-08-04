import asyncio
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import UUID

from app.providers.image.types import ImageGenerationRequest, ImageProvider, ImageResult
from app.storyboards.models import StoryboardFrame
from app.storytelling.models import Scene, Shot
from app.visual_bible.service import _generate_image_with_provider_fallback

DEFAULT_STORYBOARD_IMAGE_CONCURRENCY = 3
MAX_STORYBOARD_IMAGE_CONCURRENCY = 6


@dataclass
class StoryboardFrameGenerationPlan:
    shot: Shot
    scene: Scene
    frame_number: int
    prompt: str
    existing_frame: StoryboardFrame | None
    needs_image: bool
    asset_artifact_id: UUID
    image: ImageResult | None = None
    fallback_metadata: dict | None = None
    duration_ms: int | None = None


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
) -> None:
    semaphore = asyncio.Semaphore(storyboard_image_concurrency(concurrency))

    async def generate_plan(plan: StoryboardFrameGenerationPlan) -> None:
        if not plan.needs_image:
            return
        async with semaphore:
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
                    model=image_model,
                ),
            )
            plan.image = image
            plan.fallback_metadata = fallback_metadata
            plan.duration_ms = max(1, int((perf_counter() - generation_started_at) * 1000))

    await asyncio.gather(*(generate_plan(plan) for plan in plans if plan.needs_image))
