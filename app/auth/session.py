import base64
import hmac
import time
from hashlib import sha256

from app.config.settings import get_settings

SESSION_COOKIE_NAME = "storytelling_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 7


def _sign(value: str) -> str:
    secret = get_settings().app_secret_key.encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), sha256).hexdigest()


def create_session_token(username: str) -> str:
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{username}:{expires_at}"
    encoded_payload = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    return f"{encoded_payload}.{_sign(encoded_payload)}"


def verify_session_token(token: str) -> str | None:
    try:
        encoded_payload, signature = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(_sign(encoded_payload), signature):
        return None
    try:
        payload = base64.urlsafe_b64decode(encoded_payload.encode("ascii")).decode("utf-8")
        username, raw_expires_at = payload.rsplit(":", 1)
        expires_at = int(raw_expires_at)
    except (ValueError, UnicodeDecodeError):
        return None
    if not username or expires_at < int(time.time()):
        return None
    return username
