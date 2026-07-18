import json
import os
import secrets
import tempfile
from dataclasses import dataclass
from hashlib import pbkdf2_hmac
from pathlib import Path
from typing import Any

USERS_PATH = Path(".runtime/users.json")
PBKDF2_ITERATIONS = 210_000


@dataclass(frozen=True)
class StoredUser:
    username: str
    password_hash: str
    salt: str


def _load_payload(path: Path = USERS_PATH) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    users: dict[str, dict[str, str]] = {}
    for username, data in payload.items():
        if isinstance(data, dict):
            users[str(username).lower()] = {
                "username": str(data.get("username") or username),
                "password_hash": str(data.get("password_hash") or ""),
                "salt": str(data.get("salt") or ""),
            }
    return users


def _write_payload(payload: dict[str, dict[str, str]], path: Path = USERS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix="users-", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _password_hash(password: str, salt: str) -> str:
    digest = pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS,
    )
    return digest.hex()


def create_user(username: str, password: str, path: Path = USERS_PATH) -> StoredUser:
    normalized = username.strip().lower()
    if len(normalized) < 3:
        raise ValueError("O usuario deve ter pelo menos 3 caracteres.")
    if len(password) < 8:
        raise ValueError("A senha deve ter pelo menos 8 caracteres.")
    payload = _load_payload(path)
    if normalized in payload:
        raise ValueError("Este usuario ja existe.")
    salt = secrets.token_hex(16)
    user = StoredUser(
        username=normalized,
        password_hash=_password_hash(password, salt),
        salt=salt,
    )
    payload[normalized] = {
        "username": user.username,
        "password_hash": user.password_hash,
        "salt": user.salt,
    }
    _write_payload(payload, path)
    return user


def verify_user(username: str, password: str, path: Path = USERS_PATH) -> bool:
    normalized = username.strip().lower()
    data = _load_payload(path).get(normalized)
    if data is None:
        return False
    expected = data.get("password_hash", "")
    salt = data.get("salt", "")
    if not expected or not salt:
        return False
    return secrets.compare_digest(_password_hash(password, salt), expected)
