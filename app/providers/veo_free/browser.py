from app.providers.veo_free.session import validate_session
from app.providers.veo_free.types import VeoFreeSessionValidation


class VeoFreeBrowserClient:
    """Placeholder for future user-driven browser automation.

    This class intentionally does not bypass captcha, fingerprinting, rate limits
    or login protections. Phase 05 only verifies local session state.
    """

    def validate_local_session(self) -> VeoFreeSessionValidation:
        return validate_session()
