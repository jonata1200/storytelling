import base64
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.projects.models import User, UserSession

SESSION_COOKIE_NAME = "storytelling_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 7
PERSISTENT_SESSION_PREFIX = "sid"


def _sign(value: str) -> str:
    secret = get_settings().app_secret_key.encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), sha256).hexdigest()


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _persistent_token(session_id: UUID, secret: str) -> str:
    payload = f"{PERSISTENT_SESSION_PREFIX}:{session_id}:{secret}"
    encoded_payload = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    return f"{encoded_payload}.{_sign(encoded_payload)}"


def _persistent_session_id(token: str) -> UUID | None:
    try:
        encoded_payload, signature = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(_sign(encoded_payload), signature):
        return None
    try:
        payload = base64.urlsafe_b64decode(encoded_payload.encode("ascii")).decode("utf-8")
        prefix, raw_session_id, secret = payload.split(":", 2)
    except (ValueError, UnicodeDecodeError):
        return None
    if prefix != PERSISTENT_SESSION_PREFIX or not secret:
        return None
    try:
        return UUID(raw_session_id)
    except ValueError:
        return None


async def create_persistent_session_token(
    session: AsyncSession,
    user: User,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> str:
    expires_at = datetime.now(UTC) + timedelta(seconds=SESSION_TTL_SECONDS)
    auth_session = UserSession(
        user_id=user.id,
        email=user.email,
        token_hash="pending",
        user_agent=(user_agent or "")[:255] or None,
        ip_address=(ip_address or "")[:80] or None,
        expires_at=expires_at,
    )
    session.add(auth_session)
    await session.flush()
    if auth_session.id is None:
        auth_session.id = uuid4()
    token = _persistent_token(auth_session.id, secrets.token_urlsafe(32))
    auth_session.token_hash = _token_hash(token)
    await session.commit()
    return token


async def verify_persistent_session_token(session: AsyncSession, token: str) -> str | None:
    session_id = _persistent_session_id(token)
    if session_id is None:
        return None
    result = await session.execute(select(UserSession).where(UserSession.id == session_id))
    auth_session = result.scalars().first()
    if auth_session is None:
        return None
    if auth_session.revoked_at is not None:
        return None
    if auth_session.expires_at < datetime.now(UTC):
        return None
    if not hmac.compare_digest(auth_session.token_hash, _token_hash(token)):
        return None
    return auth_session.email


async def revoke_persistent_session_token(session: AsyncSession, token: str) -> bool:
    session_id = _persistent_session_id(token)
    if session_id is None:
        return False
    result = await session.execute(select(UserSession).where(UserSession.id == session_id))
    auth_session = result.scalars().first()
    if auth_session is None:
        return False
    auth_session.revoked_at = datetime.now(UTC)
    await session.commit()
    return True


