import hmac
import secrets
from hashlib import sha256

from app.config.settings import get_settings

CSRF_COOKIE_NAME = "storytelling_csrf"


def _sign(value: str) -> str:
    secret = get_settings().app_secret_key.encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), sha256).hexdigest()


def create_csrf_token() -> str:
    nonce = secrets.token_urlsafe(24)
    return f"{nonce}.{_sign(nonce)}"


def verify_csrf_token(cookie_token: str | None, form_token: str | None) -> bool:
    if not cookie_token or not form_token:
        return False
    if not hmac.compare_digest(cookie_token, form_token):
        return False
    try:
        nonce, signature = form_token.split(".", 1)
    except ValueError:
        return False
    return bool(nonce) and hmac.compare_digest(_sign(nonce), signature)
