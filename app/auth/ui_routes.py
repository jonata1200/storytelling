# ruff: noqa: E501

import logging
import time
from html import escape
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import CSRF_COOKIE_NAME, create_csrf_token, verify_csrf_token
from app.auth.service import authenticate_user, register_user, user_registration_available
from app.auth.session import (
    SESSION_COOKIE_NAME,
    create_persistent_session_token,
    revoke_persistent_session_token,
)
from app.config.settings import get_settings
from app.database.session import get_session

router = APIRouter(include_in_schema=False)
logger = logging.getLogger(__name__)
_AUTH_ATTEMPTS: dict[str, list[float]] = {}
AUTH_RATE_LIMIT_WINDOW_SECONDS = 60
AUTH_RATE_LIMIT_MAX_ATTEMPTS = 8
AUTH_RATE_LIMIT_SWEEP_THRESHOLD = 500


def _auth_page(
    mode: str,
    message: str = "",
    status_code: int = 200,
    registration_available: bool = False,
) -> HTMLResponse:
    is_register = mode == "register"
    title = "Criar conta" if is_register else "Entrar"
    action = "/auth/register" if is_register else "/auth/login"
    settings = get_settings()
    alternative_path = ""
    alternative_text = ""
    if registration_available:
        alternative_path = "/login" if is_register else "/register"
        alternative_text = "Já tenho conta" if is_register else "Criar uma conta"
    autocomplete = "new-password" if is_register else "current-password"
    display_name_field = (
        """
              <label for="display_name">Nome</label>
              <input id="display_name" name="display_name" autocomplete="name">
        """
        if is_register
        else ""
    )
    password_hint = (
        '<p class="hint">Use 6+ caracteres com maiúscula, minúscula, número e símbolo.</p>'
        if is_register
        else ""
    )
    escaped_message = escape(message)
    app_name = escape(settings.app_name)
    csrf_token = create_csrf_token()
    response = HTMLResponse(
        f"""
        <!doctype html>
        <html lang="pt-BR">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>{title} - {app_name}</title>
          <style>
            :root {{ color-scheme: dark; --bg:#05070c; --panel:#0c1722; --panel-2:#101f2d; --line:rgba(90,163,240,.2); --text:#eaf8ff; --muted:#86a1b2; --accent:#5aa3f0; --blue:#5aa3f0; }}
            * {{ box-sizing:border-box; }}
            body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:linear-gradient(115deg, rgba(90,163,240,.18), rgba(90,163,240,.07) 32%, transparent 58%), linear-gradient(180deg, #05070c, #08131d 48%, #04070c); color:var(--text); font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
            body::before {{ content:""; position:fixed; inset:0; pointer-events:none; background:linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px), linear-gradient(180deg, rgba(255,255,255,.025) 1px, transparent 1px); background-size:72px 72px; }}
            main {{ position:relative; width:min(420px, calc(100vw - 32px)); background:linear-gradient(180deg, rgba(20,38,54,.92), rgba(7,15,24,.96)); border:1px solid var(--line); border-radius:8px; padding:32px; box-shadow:0 0 0 1px rgba(90,163,240,.12), 0 24px 80px rgba(0,0,0,.48), 0 0 28px rgba(90,163,240,.18); }}
            img {{ width:48px; height:48px; border-radius:8px; object-fit:cover; }}
            h1 {{ margin:18px 0 6px; font-size:28px; line-height:1.1; letter-spacing:0; }}
            p {{ margin:0 0 24px; color:var(--muted); }}
            label {{ display:block; margin:16px 0 8px; color:#cbeeff; font-size:14px; }}
            input {{ width:100%; min-height:46px; border:1px solid rgba(90,163,240,.22); border-radius:8px; background:#08121c; color:var(--text); padding:0 14px; font:inherit; }}
            input:focus {{ outline:2px solid var(--accent); outline-offset:1px; box-shadow:0 0 24px rgba(90,163,240,.18); }}
            button {{ width:100%; min-height:46px; margin-top:22px; border:1px solid rgba(90,163,240,.7); border-radius:8px; background:linear-gradient(135deg, var(--accent), var(--blue)); color:#031019; font-weight:800; cursor:pointer; box-shadow:0 0 24px rgba(90,163,240,.25); }}
            a {{ color:var(--accent); text-decoration:none; }}
            .message {{ margin:0 0 12px; padding:10px 12px; border-radius:8px; background:#35231f; color:#ffcabd; border:1px solid #6c3a31; }}
            .hint {{ margin:8px 0 0; font-size:12px; line-height:1.5; color:var(--muted); }}
            .footer {{ margin-top:18px; text-align:center; font-size:14px; }}
          </style>
        </head>
        <body>
          <main>
            <img src="/ui-assets/favicon.png" alt="">
            <h1>{title}</h1>
            <p>Acesse seu estudio de storytelling.</p>
            {f'<div class="message">{escaped_message}</div>' if message else ''}
            <form method="post" action="{action}">
              <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
              {display_name_field}
              <label for="email">E-mail</label>
              <input id="email" name="email" type="email" autocomplete="email" required>
              <label for="password">Senha</label>
              <input id="password" name="password" type="password" autocomplete="{autocomplete}" required minlength="6">
              {password_hint}
              <button type="submit">{title}</button>
            </form>
            {f'<div class="footer"><a href="{alternative_path}">{alternative_text}</a></div>' if alternative_path else ''}
          </main>
        </body>
        </html>
        """,
        status_code=status_code,
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie_enabled(),
        max_age=60 * 60 * 2,
    )
    return response


def _secure_cookie_enabled() -> bool:
    return get_settings().app_env.lower() not in {"local", "development", "test"}


def _client_key(request: Request, email: str = "") -> str:
    host = request.client.host if request.client is not None else "unknown"
    return f"{host}:{email.strip().lower()}"


def _rate_limited(key: str) -> bool:
    now = time.monotonic()
    window_start = now - AUTH_RATE_LIMIT_WINDOW_SECONDS
    attempts = [item for item in _AUTH_ATTEMPTS.get(key, []) if item >= window_start]
    limited = len(attempts) >= AUTH_RATE_LIMIT_MAX_ATTEMPTS
    attempts.append(now)
    _AUTH_ATTEMPTS[key] = attempts[-AUTH_RATE_LIMIT_MAX_ATTEMPTS:]
    if len(_AUTH_ATTEMPTS) > AUTH_RATE_LIMIT_SWEEP_THRESHOLD:
        _prune_stale_auth_attempts(window_start)
    return limited


def _prune_stale_auth_attempts(window_start: float) -> None:
    for existing_key in list(_AUTH_ATTEMPTS):
        remaining = [item for item in _AUTH_ATTEMPTS[existing_key] if item >= window_start]
        if remaining:
            _AUTH_ATTEMPTS[existing_key] = remaining
        else:
            _AUTH_ATTEMPTS.pop(existing_key, None)


def _csrf_valid(cookie_token: str | None, form_token: str | None) -> bool:
    if get_settings().app_env.lower() in {"local", "test"}:
        return True
    return verify_csrf_token(cookie_token, form_token)


@router.get("/login")
async def login_page(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    return _auth_page(
        "login",
        registration_available=await user_registration_available(session),
    )


@router.get("/register")
async def register_page(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    registration_available = await user_registration_available(session)
    if not registration_available:
        return _auth_page("login", "Cadastro desativado.", status_code=403)
    return _auth_page("register", registration_available=registration_available)


@router.post("/auth/login")
async def login(
    request: Request,
    email: Annotated[str, Form(...)],
    password: Annotated[str, Form(...)],
    session: Annotated[AsyncSession, Depends(get_session)],
    csrf_token: Annotated[str, Form()] = "",
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE_NAME)] = None,
) -> Response:
    if not _csrf_valid(csrf_cookie, csrf_token):
        return _auth_page(
            "login",
            "Sessão de formulário expirada. Recarregue e tente novamente.",
            status_code=403,
            registration_available=await user_registration_available(session),
        )
    if _rate_limited(_client_key(request, email)):
        logger.warning("auth_rate_limited", extra={"operation": "login", "email": email})
        return _auth_page(
            "login",
            "Muitas tentativas. Aguarde um minuto e tente novamente.",
            status_code=429,
            registration_available=await user_registration_available(session),
        )
    user = await authenticate_user(session, email, password)
    if user is None:
        logger.warning("auth_login_failed", extra={"email": email})
        return _auth_page(
            "login",
            "E-mail ou senha inválidos.",
            registration_available=await user_registration_available(session),
        )
    token = await create_persistent_session_token(
        session,
        user,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client is not None else None,
    )
    logger.info("auth_login_succeeded", extra={"email": user.email})
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie_enabled(),
        max_age=60 * 60 * 24 * 7,
    )
    return response


@router.post("/auth/register")
async def register(
    request: Request,
    email: Annotated[str, Form(...)],
    password: Annotated[str, Form(...)],
    session: Annotated[AsyncSession, Depends(get_session)],
    display_name: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE_NAME)] = None,
) -> Response:
    registration_available = await user_registration_available(session)
    if not registration_available:
        return _auth_page("login", "Cadastro desativado.", status_code=403)
    if not _csrf_valid(csrf_cookie, csrf_token):
        return _auth_page(
            "register",
            "Sessão de formulário expirada. Recarregue e tente novamente.",
            status_code=403,
            registration_available=registration_available,
        )
    if _rate_limited(_client_key(request, email)):
        logger.warning("auth_rate_limited", extra={"operation": "register", "email": email})
        return _auth_page(
            "register",
            "Muitas tentativas. Aguarde um minuto e tente novamente.",
            status_code=429,
            registration_available=registration_available,
        )
    try:
        user = await register_user(session, email, password, display_name)
    except ValueError as exc:
        return _auth_page("register", str(exc), registration_available=registration_available)
    token = await create_persistent_session_token(
        session,
        user,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client is not None else None,
    )
    logger.info("auth_register_succeeded", extra={"email": user.email})
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie_enabled(),
        max_age=60 * 60 * 24 * 7,
    )
    return response


@router.post("/auth/logout")
async def logout(
    _request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    storytelling_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> RedirectResponse:
    if storytelling_session:
        await revoke_persistent_session_token(session, storytelling_session)
        logger.info("auth_logout")
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    response.delete_cookie(CSRF_COOKIE_NAME)
    return response
