from http.cookies import SimpleCookie

from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.dependencies import authentication_required
from app.auth.session import (
    SESSION_COOKIE_NAME,
    verify_persistent_session_token,
)
from app.database.session import AsyncSessionLocal


class UIBasicAuthMiddleware:
    """Protect NiceGUI pages when the operational API requires authentication.

    API routes keep their own FastAPI dependencies. This middleware covers the
    mounted NiceGUI app and websocket endpoints, which do not inherit those
    dependencies.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            not authentication_required()
            or scope["type"] not in {"http", "websocket"}
            or _is_public_path(str(scope.get("path") or ""))
            or await _session_username(scope) is not None
        ):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return

        response = RedirectResponse("/login", status_code=303)
        await response(scope, receive, send)


def _is_public_path(path: str) -> bool:
    return (
        path.startswith("/api/")
        or path.startswith("/auth/")
        or path.startswith("/ui-assets/")
        or path in {"/login", "/register"}
    )


async def _session_username(scope: Scope) -> str | None:
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    token = _cookie_token(headers.get("cookie", ""))
    if token is None:
        token = _bearer_token(headers.get("authorization"))
    if not token:
        return None
    try:
        async with AsyncSessionLocal() as session:
            username = await verify_persistent_session_token(session, token)
    except Exception:
        username = None
    return username


def _cookie_token(raw_cookie: str) -> str | None:
    if not raw_cookie:
        return None
    cookie = SimpleCookie()
    cookie.load(raw_cookie)
    morsel = cookie.get(SESSION_COOKIE_NAME)
    return morsel.value if morsel is not None else None


def _bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()
