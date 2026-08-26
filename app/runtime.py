"""Ajustes de runtime: política de event loop no Windows e filtros de exceção.

Centraliza a configuração do ``WindowsSelectorEventLoopPolicy`` (necessária
para subprocessos do Playwright) e o filtro de exceções de loop asyncio que
suprime ruído de sockets fechados durante shutdown.
"""

import asyncio
import logging
import sys
import weakref
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)
_INSTALLED_EXCEPTION_FILTER_LOOPS: weakref.WeakSet[asyncio.AbstractEventLoop] = weakref.WeakSet()


def configure_windows_event_loop_policy() -> None:
    if sys.platform != "win32":
        return
    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is not None:
        asyncio.set_event_loop_policy(selector_policy())


def is_benign_windows_connection_reset(exc: object) -> bool:
    if not isinstance(exc, ConnectionResetError):
        return False
    code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
    return code in {10053, 10054}


def install_asyncio_exception_filter() -> None:
    loop = asyncio.get_running_loop()
    if loop in _INSTALLED_EXCEPTION_FILTER_LOOPS:
        return
    previous_handler: Callable[[asyncio.AbstractEventLoop, dict[str, Any]], object] | None = (
        loop.get_exception_handler()
    )

    def exception_handler(
        active_loop: asyncio.AbstractEventLoop,
        context: dict[str, Any],
    ) -> None:
        exc = context.get("exception")
        if is_benign_windows_connection_reset(exc):
            logger.debug("Ignoring disconnected browser socket: %s", exc)
            return
        if previous_handler is not None:
            previous_handler(active_loop, context)
            return
        active_loop.default_exception_handler(context)

    loop.set_exception_handler(exception_handler)
    _INSTALLED_EXCEPTION_FILTER_LOOPS.add(loop)
