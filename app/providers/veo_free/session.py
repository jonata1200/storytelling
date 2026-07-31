import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config.settings import get_settings
from app.providers.veo_free.types import (
    VeoFreeSessionBundle,
    VeoFreeSessionValidation,
)

DEFAULT_SESSION_PATH = Path(".runtime/veo_free/session.json")
DEFAULT_COOKIE_NAME = "__Secure-1PSID"
DEFAULT_COOKIE_DOMAIN = ".google.com"
DEFAULT_COOKIE_TTL_DAYS = 30
AUTH_COOKIE_NAMES = (
    DEFAULT_COOKIE_NAME,
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "fern_token",
    "xi_website_user",
    "session",
)
AUTH_COOKIE_PREFIXES = (
    "wordpress_logged_in_",
    "wordpress_sec_",
)


def _session_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(get_settings().veo_ai_free_session_path or DEFAULT_SESSION_PATH)


def _parse_cookie_bundle(bundle: str | dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(bundle, str):
        try:
            parsed = json.loads(bundle)
        except json.JSONDecodeError as exc:
            raise ValueError("Bundle de cookie Veo AI Free deve ser JSON valido.") from exc
    else:
        parsed = bundle
    if isinstance(parsed, list):
        parsed = {"cookies": parsed}
    if isinstance(parsed, dict):
        cookies = parsed.get("cookies")
        if isinstance(cookies, list):
            normalized_cookies: list[Any] = []
            for cookie in cookies:
                if isinstance(cookie, dict) and "expires" not in cookie:
                    cookie = dict(cookie)
                    if "expirationDate" in cookie:
                        cookie["expires"] = cookie["expirationDate"]
                normalized_cookies.append(cookie)
            parsed = {**parsed, "cookies": normalized_cookies}
        return parsed
    raise ValueError("Bundle de cookie Veo AI Free deve ser um objeto ou lista JSON.")


def _ensure_no_control_chars(value: Any) -> None:
    if isinstance(value, str):
        if "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError("Bundle de cookie Veo AI Free contem caractere de controle.")
    elif isinstance(value, dict):
        for item in value.values():
            _ensure_no_control_chars(item)
    elif isinstance(value, list):
        for item in value:
            _ensure_no_control_chars(item)


def _parse_cookie_header_or_value(cookie_value: str) -> list[dict[str, Any]]:
    cleaned = cookie_value.strip()
    if not cleaned:
        raise ValueError("Informe o valor do cookie Veo AI Free.")

    expires = (datetime.now(UTC) + timedelta(days=DEFAULT_COOKIE_TTL_DAYS)).timestamp()
    if "=" not in cleaned:
        return [
            {
                "name": DEFAULT_COOKIE_NAME,
                "value": cleaned,
                "domain": DEFAULT_COOKIE_DOMAIN,
                "path": "/",
                "expires": expires,
                "secure": True,
                "httpOnly": True,
            }
        ]

    cookies: list[dict[str, Any]] = []
    for item in cleaned.split(";"):
        name, separator, value = item.strip().partition("=")
        if not separator or not name.strip() or not value.strip():
            continue
        cookies.append(
            {
                "name": name.strip(),
                "value": value.strip(),
                "domain": DEFAULT_COOKIE_DOMAIN,
                "path": "/",
                "expires": expires,
                "secure": True,
                "httpOnly": True,
            }
        )
    if not cookies:
        raise ValueError("Informe um valor de cookie ou um cabecalho Cookie valido.")
    return cookies


def save_cookie_value(
    cookie_value: str,
    path: Path | str | None = None,
) -> VeoFreeSessionValidation:
    payload = {
        "cookies": _parse_cookie_header_or_value(cookie_value),
        "source": "manual_cookie_value",
    }
    return save_cookie_bundle(payload, path)


def save_cookie_bundle(
    bundle: str | dict[str, Any] | list[dict[str, Any]],
    path: Path | str | None = None,
) -> VeoFreeSessionValidation:
    payload = _parse_cookie_bundle(bundle)
    _ensure_no_control_chars(payload)
    payload.setdefault("saved_at", datetime.now(UTC).isoformat())
    payload.setdefault("source", "manual")
    try:
        session = VeoFreeSessionBundle.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("Bundle de cookie Veo AI Free fora do formato esperado.") from exc
    if not session.cookies:
        raise ValueError("Bundle de cookie Veo AI Free precisa ter ao menos um cookie.")

    target = _session_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix="veo-session-",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(session.model_dump(), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return validate_session(target)


def _auth_cookie_names(cookies: list[Any]) -> list[str]:
    names: list[str] = []
    for cookie in cookies:
        name = str(getattr(cookie, "name", "") or "").strip()
        if not name:
            continue
        if name in AUTH_COOKIE_NAMES or any(
            name.startswith(prefix) for prefix in AUTH_COOKIE_PREFIXES
        ):
            names.append(name)
    return names


def load_cookie_bundle(path: Path | str | None = None) -> VeoFreeSessionBundle | None:
    target = _session_path(path)
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return VeoFreeSessionBundle.model_validate(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError):
        return None


def clear_session(path: Path | str | None = None) -> None:
    _session_path(path).unlink(missing_ok=True)


def validate_session(path: Path | str | None = None) -> VeoFreeSessionValidation:
    target = _session_path(path)
    session = load_cookie_bundle(target)
    if session is None:
        return VeoFreeSessionValidation(
            status="unknown",
            message="Sessao Veo AI Free nao configurada.",
            details={"configured": "false"},
        )
    auth_cookie_names = _auth_cookie_names(session.cookies)
    if not auth_cookie_names:
        return VeoFreeSessionValidation(
            status="unknown",
            message=(
                "Sessao Veo AI Free salva, mas nenhum cookie de login conhecido foi encontrado."
            ),
            details={
                "configured": "true",
                "cookie_count": str(len(session.cookies)),
                "has_user_agent": str(bool(session.user_agent)).lower(),
                "auth_cookie_names": "",
            },
        )
    now = datetime.now(UTC).timestamp()
    expiring_cookies = [
        float(cookie.expires)
        for cookie in session.cookies
        if cookie.expires is not None and float(cookie.expires) > 0
    ]
    if expiring_cookies and max(expiring_cookies) <= now:
        return VeoFreeSessionValidation(
            status="expired",
            message="Sessao Veo AI Free expirada; reconecte manualmente.",
            details={
                "configured": "true",
                "cookie_count": str(len(session.cookies)),
                "has_user_agent": str(bool(session.user_agent)).lower(),
                "auth_cookie_names": ", ".join(auth_cookie_names),
            },
        )
    if not expiring_cookies:
        return VeoFreeSessionValidation(
            status="unknown",
            message="Sessao Veo AI Free salva, mas sem expiracao verificavel.",
            details={
                "configured": "true",
                "cookie_count": str(len(session.cookies)),
                "has_user_agent": str(bool(session.user_agent)).lower(),
                "auth_cookie_names": ", ".join(auth_cookie_names),
            },
        )
    return VeoFreeSessionValidation(
        status="connected",
        message="Sessao Veo AI Free parece valida localmente.",
        details={
            "configured": "true",
            "cookie_count": str(len(session.cookies)),
            "has_user_agent": str(bool(session.user_agent)).lower(),
            "auth_cookie_names": ", ".join(auth_cookie_names),
        },
    )
