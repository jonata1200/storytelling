"""Secret de app gerado e persistido localmente (SEC-03).

Em ambiente local sem APP_SECRET_KEY, um segredo aleatório é gerado na primeira
carga das settings e persistido em ``.runtime/app_secret_key``. Isso cessa o
aviso repetido de secret default e elimina sessões/CSRF assinados com o valor
conhecido do repositório ("change-me-in-development"). Ambientes não-locais
continuam exigindo APP_SECRET_KEY explícita.
"""

import secrets
from pathlib import Path

SECRET_KEY_FILENAME = Path(".runtime") / "app_secret_key"


def load_or_create_local_secret_key(storage_root: Path) -> str:
    """Carrega (ou cria) o secret de app persistido para uso local.

    O arquivo fica ao lado do storage configurado: ``<repo>/.runtime/app_secret_key``.
    """
    secret_path = storage_root.parent / SECRET_KEY_FILENAME
    try:
        existing = secret_path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    generated = secrets.token_urlsafe(48)
    try:
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        secret_path.write_text(generated, encoding="utf-8")
    except OSError:
        # Sem acesso ao disco para persistir: um segredo por processo ainda é
        # melhor que o default conhecido do repositório.
        return generated
    return generated