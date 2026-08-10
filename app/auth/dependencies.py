from typing import Annotated

from fastapi import Cookie, Header, HTTPException, Request, status

from app.auth.session import (
    SESSION_COOKIE_NAME,
    verify_persistent_session_token,
)
from app.config.settings import get_settings
from app.database.session import AsyncSessionLocal

LOCAL_AUTH_BYPASS_ENVS = {"local", "test"}


def authentication_required() -> bool:
    return get_settings().app_env.lower() not in LOCAL_AUTH_BYPASS_ENVS


def _authorization_token(value: str | None) -> str | None:
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def require_authenticated_user(
    _request: Request,
    storytelling_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if not authentication_required():
        return "local-user"

    token = storytelling_session or _authorization_token(authorization)
    username = None
    if token:
        try:
            async with AsyncSessionLocal() as session:
                username = await verify_persistent_session_token(session, token)
        except Exception:
            username = None
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


async def require_basic_auth(
    request: Request,
    storytelling_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    return await require_authenticated_user(request, storytelling_session, authorization)
