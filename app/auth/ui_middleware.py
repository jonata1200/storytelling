import base64
import secrets
from http.cookies import SimpleCookie

from starlette.datastructures import Headers
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.session import SESSION_COOKIE_NAME, verify_session_token
from app.config.settings import get_settings


class UIBasicAuthMiddleware:
    """Protect NiceGUI HTTP and websocket endpoints with UI sessions."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    def _public_paths(self) -> set[str]:
        public_paths = {
            "/auth/login",
            "/auth/logout",
            "/login",
        }
        if get_settings().allow_user_registration:
            public_paths.update({"/auth/register", "/register"})
        return public_paths

    def _is_ui_scope(self, scope: Scope) -> bool:
        path = str(scope.get("path", ""))
        return (
            not path.startswith("/api/")
            and not path.startswith("/ui-assets/")
            and path not in self._public_paths()
        )

    @staticmethod
    def _session_authorized(scope: Scope) -> bool:
        headers = Headers(raw=scope.get("headers", []))
        cookies = SimpleCookie()
        cookies.load(headers.get("cookie", ""))
        cookie = cookies.get(SESSION_COOKIE_NAME)
        if cookie is None:
            return False
        return verify_session_token(cookie.value) is not None

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
