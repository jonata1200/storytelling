# ruff: noqa: E501

from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.auth.session import SESSION_COOKIE_NAME, create_session_token
from app.auth.user_store import create_user, verify_user
from app.config.settings import get_settings

router = APIRouter(include_in_schema=False)


def _auth_page(mode: str, message: str = "") -> HTMLResponse:
    is_register = mode == "register"
    title = "Criar conta" if is_register else "Entrar"
    action = "/auth/register" if is_register else "/auth/login"
    alternative_path = "/login" if is_register else "/register"
    alternative_text = "Ja tenho conta" if is_register else "Criar uma conta"
    autocomplete = "new-password" if is_register else "current-password"
    escaped_message = escape(message)
    app_name = escape(get_settings().app_name)
    return HTMLResponse(
        f"""
        <!doctype html>
        <html lang="pt-BR">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>{title} - {app_name}</title>
          <style>
            :root {{ color-scheme: dark; --bg:#090b0a; --panel:#151816; --line:#2a302b; --text:#f4f5f2; --muted:#969c97; --accent:#5898d4; }}
            * {{ box-sizing:border-box; }}
            body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:var(--bg); color:var(--text); font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
            main {{ width:min(420px, calc(100vw - 32px)); background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:32px; box-shadow:0 24px 80px rgba(0,0,0,.35); }}
            img {{ width:48px; height:48px; border-radius:8px; object-fit:cover; }}
            h1 {{ margin:18px 0 6px; font-size:28px; line-height:1.1; letter-spacing:0; }}
            p {{ margin:0 0 24px; color:var(--muted); }}
            label {{ display:block; margin:16px 0 8px; color:#d9dcd9; font-size:14px; }}
            input {{ width:100%; min-height:46px; border:1px solid #343a35; border-radius:8px; background:#0f1210; color:var(--text); padding:0 14px; font:inherit; }}
            input:focus {{ outline:2px solid var(--accent); outline-offset:1px; }}
            button {{ width:100%; min-height:46px; margin-top:22px; border:0; border-radius:8px; background:var(--accent); color:#081015; font-weight:700; cursor:pointer; }}
            a {{ color:var(--accent); text-decoration:none; }}
            .message {{ margin:0 0 12px; padding:10px 12px; border-radius:8px; background:#35231f; color:#ffcabd; border:1px solid #6c3a31; }}
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
              <label for="username">Usuario</label>
              <input id="username" name="username" autocomplete="username" required minlength="3">
              <label for="password">Senha</label>
              <input id="password" name="password" type="password" autocomplete="{autocomplete}" required minlength="8">
              <button type="submit">{title}</button>
            </form>
            <div class="footer"><a href="{alternative_path}">{alternative_text}</a></div>
          </main>
        </body>
        </html>
        """
    )


def _secure_cookie_enabled() -> bool:
    return get_settings().app_env.lower() not in {"local", "development", "test"}


@router.get("/login")
async def login_page() -> HTMLResponse:
    return _auth_page("login")


@router.get("/register")
async def register_page() -> HTMLResponse:
    return _auth_page("register")


@router.post("/auth/login")
async def login(username: str = Form(...), password: str = Form(...)) -> Response:
    if not verify_user(username, password):
        return _auth_page("login", "Usuario ou senha invalidos.")
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(username.strip().lower()),
        httponly=True,
        samesite="lax",
        secure=_secure_cookie_enabled(),
        max_age=60 * 60 * 24 * 7,
    )
    return response


@router.post("/auth/register")
async def register(
    username: str = Form(...), password: str = Form(...)
) -> Response:
    try:
        user = create_user(username, password)
    except ValueError as exc:
        return _auth_page("register", str(exc))
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user.username),
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
