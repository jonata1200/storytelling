"""Camada de autenticacao por token compartilhado para endpoints privados.

A aplicacao é local e single-user, mas expor endpoints sem qualquer autenticacao
permite que qualquer cliente na rede dispare gastos de IA, mute orçamentos,
leia telemetria e delete arquivos. Esta camada introduz um token simples
(`APP_API_TOKEN`) que pode ser definido no .env ou pela UI de Configuracoes.

Em ambientes `local`/`development`/`test` sem token configurado, a autenticacao
é relaxada (nao bloqueia) para preservar o fluxo de desenvolvimento, mas um
aviso é emitido. Em ambientes nao-locais sem token, a aplicacao recusa iniciar.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_API_TOKEN_HEADER = APIKeyHeader(name="x-api-token", auto_error=False)

# Constantes avaliadas em runtime para evitar import-time side effects.
_LOCAL_ENVS = frozenset({"local", "development", "test"})


def configured_api_token() -> str | None:
    """Retorna o token de API configurado, se houver.

    Prioridade: env ``APP_API_TOKEN`` > preferencia runtime ``APP_API_TOKEN``.
    """
    env_token = os.environ.get("APP_API_TOKEN", "").strip()
    if env_token:
        return env_token
    settings = get_settings()
    runtime_token = str(getattr(settings, "app_api_token", "") or "").strip()
    return runtime_token or None


def _is_local_env() -> bool:
    return get_settings().app_env.lower() in _LOCAL_ENVS


def _constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


async def verify_api_token(token: str | None = Depends(_API_TOKEN_HEADER)) -> None:
    """Dependencia FastAPI que valida o token compartilhado.

    - Se token configurado: exige header ``x-api-token`` com valor igual.
    - Se nao configurado em env local: permite (aviso logado uma vez).
    - Se nao configurado em env nao-local: recusa 401.
    """
    expected = configured_api_token()
    if expected is None:
        if _is_local_env():
            logger.debug(
                "auth_layer_relaxed: APP_API_TOKEN nao configurado em env local; "
                "endpoints privados sem autenticacao."
            )
            return
        raise HTTPException(
            status_code=401,
            detail="Autenticacao exigida: configure APP_API_TOKEN para acessar endpoints privados.",
        )
    if token is None or not _constant_time_equals(str(token or "").strip(), expected):
        raise HTTPException(status_code=401, detail="Token de API invalido ou ausente.")


async def verify_api_token_optional(request: Request) -> None:
    """Validacao via middleware para cobrir rotas nao-cobertas por Depends.

    Usada quando o router inclui dependencias via ``APIRouter(dependencies=...)``.
    """
    expected = configured_api_token()
    if expected is None:
        if _is_local_env():
            return
        raise HTTPException(status_code=401, detail="APP_API_TOKEN nao configurado.")
    token = request.headers.get("x-api-token", "").strip()
    if not token or not _constant_time_equals(token, expected):
        raise HTTPException(status_code=401, detail="Token de API invalido ou ausente.")


def fingerprint_token(token: str) -> str:
    """Retorna um fingerprint curto (nao reversivel) do token para logs."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def auth_status() -> dict[str, Any]:
    """Estado da auth para diagnostico (nao expoe o token)."""
    token = configured_api_token()
    return {
        "enabled": token is not None,
        "fingerprint": fingerprint_token(token) if token else None,
        "local_env": _is_local_env(),
    }
