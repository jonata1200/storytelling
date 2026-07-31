from dataclasses import dataclass

from app.providers.veo_free.session import validate_session
from app.providers.veo_free.types import VeoFreeSessionValidation

VEO_FREE_GENERATION_UNAVAILABLE_MESSAGE = (
    "Veo AI Free experimental ainda precisa de descoberta manual de endpoint "
    "ou automacao assistida pelo usuario antes de gerar midia real."
)


class VeoFreeGenerationUnavailableError(RuntimeError):
    """Raised when the local Veo session exists but real generation is not wired yet."""


def veo_free_generation_available() -> bool:
    return False


@dataclass(frozen=True)
class VeoFreeGeneratedMedia:
    media_bytes: bytes
    content_type: str
    external_job_id: str
    metadata: dict


class VeoFreeBrowserClient:
    """Placeholder for future user-driven browser automation.

    This class intentionally does not bypass captcha, fingerprinting, rate limits
    or login protections. Phase 05 only verifies local session state.
    """

    def validate_local_session(self) -> VeoFreeSessionValidation:
        return validate_session()

    async def generate_image(self, payload: dict) -> VeoFreeGeneratedMedia:
        _ = payload
        raise VeoFreeGenerationUnavailableError(VEO_FREE_GENERATION_UNAVAILABLE_MESSAGE)

    async def generate_video(self, payload: dict) -> VeoFreeGeneratedMedia:
        _ = payload
        raise VeoFreeGenerationUnavailableError(VEO_FREE_GENERATION_UNAVAILABLE_MESSAGE)
