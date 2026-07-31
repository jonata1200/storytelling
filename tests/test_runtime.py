import asyncio
from typing import Any

import pytest

import app.runtime as runtime
from app.runtime import (
    install_asyncio_exception_filter,
    is_benign_windows_connection_reset,
)


def test_is_benign_windows_connection_reset_checks_winerror_code() -> None:
    assert is_benign_windows_connection_reset(ConnectionResetError(10054, "reset"))
    assert not is_benign_windows_connection_reset(ConnectionResetError(104, "reset"))
    assert not is_benign_windows_connection_reset(RuntimeError("boom"))


@pytest.mark.asyncio
async def test_asyncio_exception_filter_ignores_browser_connection_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    runtime._INSTALLED_EXCEPTION_FILTER_LOOPS.clear()
    loop.set_exception_handler(None)
    monkeypatch.setattr(loop, "default_exception_handler", lambda context: calls.append(context))

    install_asyncio_exception_filter()
    loop.call_exception_handler({"exception": ConnectionResetError(10054, "reset")})

    assert calls == []


@pytest.mark.asyncio
async def test_asyncio_exception_filter_delegates_real_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    runtime._INSTALLED_EXCEPTION_FILTER_LOOPS.clear()
    loop.set_exception_handler(None)
    monkeypatch.setattr(loop, "default_exception_handler", lambda context: calls.append(context))

    install_asyncio_exception_filter()
    context = {"exception": RuntimeError("boom")}
    loop.call_exception_handler(context)

    assert calls == [context]
