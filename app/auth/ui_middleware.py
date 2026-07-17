import base64
import secrets

from starlette.datastructures import Headers
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.session import SESSION_COOKIE_NAME, verify_session_token
from app.config.settings import get_settings


class UIBasicAuthMiddleware:
    """Protect NiceGUI HTTP and websocket endpoints with UI sessions."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _is_ui_scope(scope: Scope) -> bool:
        path = str(scope.get("path", ""))
        public_paths = {
            "/auth/login",
            "/auth/logout",
            "/auth/register",
            "/docs",
            "/login",
            "/openapi.json",
            "/redoc",
            "/register",
        }
        return (
            not path.startswith("/api/")
            and not path.startswith("/ui-assets/")
            and path not in public_paths
        )

    @staticmethod
    def _session_authorized(scope: Scope) -> bool:
        headers = Headers(raw=scope.get("headers", []))
        cookies = headers.get("cookie", "")
        cookie_prefix = f"{SESSION_COOKIE_NAME}="
        if cookie_prefix not in cookies:
            return False
        token = cookies.split(cookie_prefix, 1)[-1].split(";", 1)[0]
        return verify_session_token(token) is not None

    @staticmethod
    def _basic_authorized(scope: Scope) -> bool:
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"")
        if not authorization.startswith(b"Basic "):
            return False
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return False
        settings = get_settings()
        username_ok = secrets.compare_digest(username, settings.api_basic_username)
        password_ok = secrets.compare_digest(password, settings.api_basic_password)
        return username_ok and password_ok

    @classmethod
    def _authorized(cls, scope: Scope) -> bool:
        return cls._session_authorized(scope) or cls._basic_authorized(scope)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"} or not self._is_ui_scope(scope):
            await self.app(scope, receive, send)
            return
        if self._authorized(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        response = RedirectResponse("/login", status_code=303)
        await response(scope, receive, send)
