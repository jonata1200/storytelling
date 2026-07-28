# ruff: noqa: E501

from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import authenticate_user, register_user
from app.auth.session import SESSION_COOKIE_NAME, create_session_token
from app.config.settings import get_settings
from app.database.session import get_session

router = APIRouter(include_in_schema=False)


def _auth_page(mode: str, message: str = "", status_code: int = 200) -> HTMLResponse:
    is_register = mode == "register"
    title = "Criar conta" if is_register else "Entrar"
    action = "/auth/register" if is_register else "/auth/login"
    settings = get_settings()
    alternative_path = ""
    alternative_text = ""
    if settings.allow_user_registration:
        alternative_path = "/login" if is_register else "/register"
        alternative_text = "Ja tenho conta" if is_register else "Criar uma conta"
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
        '<p class="hint">Use 6+ caracteres com maiuscula, minuscula, numero e simbolo.</p>'
        if is_register
        else ""
    )
    escaped_message = escape(message)
    app_name = escape(settings.app_name)
    return HTMLResponse(
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


def _secure_cookie_enabled() -> bool:
    return get_settings().app_env.lower() not in {"local", "development", "test"}


@router.get("/login")
async def login_page() -> HTMLResponse:
    return _auth_page("login")


@router.get("/register")
async def register_page() -> HTMLResponse:
    if not get_settings().allow_user_registration:
        return _auth_page("login", "Cadastro desativado.", status_code=403)
    return _auth_page("register")


@router.post("/auth/login")
async def login(
    email: Annotated[str, Form(...)],
    password: Annotated[str, Form(...)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    user = await authenticate_user(session, email, password)
    if user is None:
        return _auth_page("login", "E-mail ou senha invalidos.")
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user.email),
        httponly=True,
        samesite="lax",
        secure=_secure_cookie_enabled(),
        max_age=60 * 60 * 24 * 7,
    )
    return response


@router.post("/auth/register")
async def register(
    email: Annotated[str, Form(...)],
    password: Annotated[str, Form(...)],
    session: Annotated[AsyncSession, Depends(get_session)],
    display_name: Annotated[str, Form()] = "",
) -> Response:
    if not get_settings().allow_user_registration:
        return _auth_page("login", "Cadastro desativado.", status_code=403)
    try:
        user = await register_user(session, email, password, display_name)
    except ValueError as exc:
        return _auth_page("register", str(exc))
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user.email),
        httponly=True,
        samesite="lax",
        secure=_secure_cookie_enabled(),
        max_age=60 * 60 * 24 * 7,
    )
    return response


@router.post("/auth/logout")
async def logout(_request: Request) -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
