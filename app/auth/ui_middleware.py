import base64
import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config.settings import get_settings


class UIBasicAuthMiddleware:
    """Protect NiceGUI HTTP and websocket endpoints with the configured credentials."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _is_ui_scope(scope: Scope) -> bool:
        path = str(scope.get("path", ""))
        return not path.startswith("/api/") and path not in {"/docs", "/openapi.json", "/redoc"}

    @staticmethod
    def _authorized(scope: Scope) -> bool:
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
        response = JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
        )
        await response(scope, receive, send)
