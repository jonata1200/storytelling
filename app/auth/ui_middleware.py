from starlette.types import ASGIApp, Receive, Scope, Send


class UIBasicAuthMiddleware:
    """Legacy compatibility middleware.

    Authentication is disabled for this personal-use application, so the middleware
    now forwards every request unchanged if an old import wires it in.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
