import re
import secrets
from hashlib import pbkdf2_hmac

PBKDF2_ITERATIONS = 260_000
PASSWORD_MIN_LENGTH = 6
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("Informe um e-mail válido.")
    return email


def validate_strong_password(password: str, email: str | None = None) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError("A senha deve ter pelo menos 6 caracteres.")
    if any(character.isspace() for character in password):
        raise ValueError("A senha não deve conter espaços.")
    checks = (
        (r"[a-z]", "uma letra minúscula"),
        (r"[A-Z]", "uma letra maiúscula"),
        (r"\d", "um número"),
        (r"[^A-Za-z0-9]", "um símbolo"),
    )
    missing = [message for pattern, message in checks if re.search(pattern, password) is None]
    if missing:
        raise ValueError("A senha deve conter " + ", ".join(missing) + ".")
    if email:
        local_part = normalize_email(email).split("@", 1)[0]
        if local_part and local_part.lower() in password.lower():
            raise ValueError("A senha não deve conter partes do e-mail.")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, raw_iterations, salt, expected = stored_hash.split("$", 3)
        iterations = int(raw_iterations)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256" or iterations <= 0:
        return False
    try:
        salt_bytes = bytes.fromhex(salt)
    except ValueError:
        return False
    digest = pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        iterations,
    ).hex()
    return secrets.compare_digest(digest, expected)
