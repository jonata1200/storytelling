import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def current_correlation_id() -> str | None:
    return correlation_id_var.get()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = request.headers.get("x-correlation-id") or uuid4().hex
        token = correlation_id_var.set(correlation_id)
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        response.headers["x-correlation-id"] = correlation_id
        response.headers["x-process-time-ms"] = str(duration_ms)
        return response
