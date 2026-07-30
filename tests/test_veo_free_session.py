from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.providers.veo_free.session import (
    clear_session,
    load_cookie_bundle,
    save_cookie_bundle,
    validate_session,
)


def test_veo_free_session_save_validate_and_clear(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    expires = (datetime.now(UTC) + timedelta(hours=1)).timestamp()

    validation = save_cookie_bundle(
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "secret-cookie",
                    "domain": "veo.example",
                    "expires": expires,
                }
            ],
            "user_agent": "Mozilla/5.0",
        },
        path,
    )

    assert validation.status == "connected"
    assert validation.details["cookie_count"] == "1"
    loaded = load_cookie_bundle(path)
    assert loaded is not None
    assert loaded.cookies[0].name == "session"

    clear_session(path)
    assert validate_session(path).status == "unknown"


def test_veo_free_session_reports_expired_cookie(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    expires = (datetime.now(UTC) - timedelta(hours=1)).timestamp()

    validation = save_cookie_bundle(
        [{"name": "session", "value": "secret-cookie", "expires": expires}],
        path,
    )

    assert validation.status == "expired"


def test_veo_free_session_accepts_browser_expiration_date(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    expires = (datetime.now(UTC) + timedelta(hours=1)).timestamp()

    validation = save_cookie_bundle(
        [{"name": "session", "value": "secret-cookie", "expirationDate": expires}],
        path,
    )

    assert validation.status == "connected"


def test_veo_free_session_rejects_invalid_or_empty_bundle(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="JSON valido"):
        save_cookie_bundle("{broken", tmp_path / "session.json")

    with pytest.raises(ValueError, match="ao menos um cookie"):
        save_cookie_bundle({"cookies": []}, tmp_path / "session.json")

    with pytest.raises(ValueError, match="caractere de controle"):
        save_cookie_bundle(
            {"cookies": [{"name": "session", "value": "secret\ncookie"}]},
            tmp_path / "session.json",
        )
