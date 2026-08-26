import re
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


def current_correlation_id() -> str | None:
    return correlation_id_var.get()


def _sanitize_correlation_id(raw: str | None) -> str:
    if raw and _CORRELATION_ID_PATTERN.match(raw):
        return raw
    return uuid4().hex


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = _sanitize_correlation_id(request.headers.get("x-correlation-id"))
        token = correlation_id_var.set(correlation_id)
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            response.headers["x-correlation-id"] = correlation_id
            response.headers["x-process-time-ms"] = str(duration_ms)
            return response
        finally:
            correlation_id_var.reset(token)
