"""Tests for the API token authentication layer (app/core/auth.py).

These are unit tests that verify:
- Token validation logic (correct token accepted, wrong/missing rejected)
- Local env relaxation (no token configured = allowed in local/dev/test)
- Non-local env rejection (no token = 401)
- Fingerprint is non-reversible
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.auth import (
    auth_status,
    configured_api_token,
    fingerprint_token,
    verify_api_token,
)


def _make_settings(app_env: str = "local", app_api_token: str = "") -> SimpleNamespace:
    return SimpleNamespace(app_env=app_env, app_api_token=app_api_token)


@pytest.mark.unit
def test_fingerprint_is_non_reversible():
    fp = fingerprint_token("my-secret-token")
    assert fp != "my-secret-token"
    assert len(fp) == 12


@pytest.mark.unit
def test_fingerprint_consistent():
    assert fingerprint_token("abc") == fingerprint_token("abc")


@pytest.mark.unit
def test_auth_status_disabled_in_local_without_token():
    with patch("app.core.auth.get_settings", return_value=_make_settings("local")):
        with patch.dict(os.environ, {}, clear=True):
            status = auth_status()
    assert status["enabled"] is False
    assert status["local_env"] is True


@pytest.mark.unit
def test_auth_status_enabled_with_token():
    with patch("app.core.auth.get_settings", return_value=_make_settings("local", "tok123")):
        with patch.dict(os.environ, {}, clear=True):
            status = auth_status()
    assert status["enabled"] is True
    assert status["fingerprint"] is not None


@pytest.mark.asyncio
@pytest.mark.unit
async def test_verify_api_token_accepts_correct_token():
    with patch("app.core.auth.get_settings", return_value=_make_settings("local", "my-token")):
        with patch.dict(os.environ, {}, clear=True):
            # Should not raise
            await verify_api_token(token="my-token")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_verify_api_token_rejects_wrong_token():
    from fastapi import HTTPException

    with patch("app.core.auth.get_settings", return_value=_make_settings("local", "my-token")):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_token(token="wrong-token")
            assert exc_info.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.unit
async def test_verify_api_token_rejects_missing_token():
    from fastapi import HTTPException

    with patch("app.core.auth.get_settings", return_value=_make_settings("local", "my-token")):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_token(token=None)
            assert exc_info.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.unit
async def test_verify_api_token_relaxed_in_local_without_configured_token():
    with patch("app.core.auth.get_settings", return_value=_make_settings("local", "")):
        with patch.dict(os.environ, {}, clear=True):
            # Should not raise — local env without token is relaxed
            await verify_api_token(token=None)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_verify_api_token_rejects_in_non_local_without_token():
    from fastapi import HTTPException

    with patch("app.core.auth.get_settings", return_value=_make_settings("production", "")):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_token(token=None)
            assert exc_info.value.status_code == 401


@pytest.mark.unit
def test_configured_api_token_from_env():
    with patch.dict(os.environ, {"APP_API_TOKEN": "env-token-123"}):
        with patch("app.core.auth.get_settings", return_value=_make_settings("local")):
            token = configured_api_token()
    assert token == "env-token-123"


@pytest.mark.unit
def test_configured_api_token_from_settings():
    with patch.dict(os.environ, {}, clear=True):
        with patch(
            "app.core.auth.get_settings",
            return_value=_make_settings("local", "settings-token"),
        ):
            token = configured_api_token()
    assert token == "settings-token"