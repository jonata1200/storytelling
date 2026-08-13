# Fase 2 — Remoção do sistema de autenticação

## Objetivo

Remover todo o sistema de autenticação: módulo `app/auth/`, modelos de usuário/sessão, dependência nas rotas da API, middleware de UI e botões de logout. A aplicação passa a não exigir login em nenhum ambiente.

## Contexto / mapa de impacto

- Módulo `app/auth/`: `csrf.py`, `dependencies.py`, `passwords.py`, `router.py`, `service.py`, `session.py`, `ui_middleware.py`, `ui_routes.py`.
- Modelos `User` e `UserSession` em `app/projects/models.py`; FKs para `users.id` em `workspaces.owner_user_id`, `approvals.reviewer_user_id` e `clip_reviews.reviewer_user_id` (`app/video_generation/models.py`).
- `app/factory.py`: registra `UIBasicAuthMiddleware` e `auth_ui_router`.
- `app/api/router.py`: `private_api_router` com `dependencies=[Depends(require_authenticated_user)]`; inclui `auth_router`.
- `app/api/health.py`: usa `require_authenticated_user`.
- `app/approvals/service.py`: aceita `reviewer_user_id`.
- UI: `app/ui/layout/navigation.py` (`logout_button` e usos na sidebar desktop/mobile).
- Settings: `allow_user_registration`, `single_user_mode` (mantidos: `app_secret_key`, pois o NiceGUI usa como `storage_secret`).
- Testes: `tests/test_auth.py` e referências a auth em outros testes.

## Checklist de ações

### Código de aplicação
- [x] Remover o diretório `app/auth/` por completo.
- [x] `app/factory.py`: remover imports e uso de `UIBasicAuthMiddleware` e `auth_ui_router`.
- [x] `app/api/router.py`: remover `require_authenticated_user` da definição do `private_api_router` e remover o `auth_router` (também removeu o import `Depends` ocioso).
- [x] `app/api/health.py`: remover a dependência `require_authenticated_user`.
- [x] `app/projects/models.py`: remover as classes `User` e `UserSession` (e imports `datetime`/`DateTime` ociosos).
- [x] Remover as colunas de FK órfãs (código SQLAlchemy — a migração fica na Fase 6):
      - [x] `Workspace.owner_user_id`
      - [x] `Approval.reviewer_user_id`
      - [x] `ClipReview.reviewer_user_id` (`app/video_generation/models.py`)
- [x] `app/approvals/service.py`: remover o parâmetro `reviewer_user_id` e seus usos (nenhum chamador passava o parâmetro).
- [x] `app/config/settings.py`: remover `allow_user_registration` e `single_user_mode`.
- [x] `.env.example`: remover `ALLOW_USER_REGISTRATION` e `SINGLE_USER_MODE`.
- [x] `app/config/runtime_preferences.py`: conferir — não possuía `allow_user_registration`/`single_user_mode` em `PREFERENCE_KEYS`; nada a remover.

### UI
- [x] `app/ui/layout/navigation.py`: remover `logout_button` e as duas chamadas (desktop sidebar e mobile bottom nav) em `home_sidebar`.
- [x] Procurar outros botões/links de login/logout na UI (ex.: `fetch('/auth/logout')`) e removê-los — nenhum outro encontrado.
- [x] Conferir se existe página/rota de login/registro fora de `app/auth/` — não existe.

### Testes
- [x] Remover `tests/test_auth.py` (18 testes).
- [x] Atualizar/remover referências a `app.auth` em outros testes — `tests/conftest.py` teve `test_auth.py` removido dos conjuntos de markers (`security`, `ui`, `integration`); os demais testes não usam `app.auth`.

### Verificação de resíduos
- [x] Buscar e zerar referências remanescentes (fora de `docs/` e de migrações antigas):
      `from app.auth`, `app.auth.`, `UserSession`, `password_hash`, `require_authenticated_user`,
      `require_basic_auth`, `UIBasicAuthMiddleware`, `storytelling_session`, `allow_user_registration`,
      `single_user_mode`, `/auth/login`, `/auth/logout`, `/login`, `/register` — **zero ocorrências** em `app/` e `tests/` (restam apenas em `alembic/versions/` e `docs/`).
- [x] Rodar `uv run pytest` — **533 passed, 5 failed (pré-existentes), 5 skipped**.
- [x] Rodar `uv run mypy .` — **18 erros (mesmos do baseline)** e `uv run ruff check .` — **All checks passed**.

## Critérios de saída

- [x] Zero referências a `app.auth`/modelos de usuário no código (exceto docs e migrações antigas).
- [x] A API inicia sem exigir autenticação; `/api/v1/health` responde sem token (rota `/ready` sem dependência de auth; validação manual completa na Fase 7).
- [x] Suíte de testes, mypy e ruff verdes (mypy mantém apenas os 18 erros pré-existentes).
- [x] Não há botão "Sair" nem fluxo de login/registro na UI.

## Riscos e notas

- **NiceGUI storage**: `app_secret_key` continua sendo usado como `storage_secret` do NiceGUI — não remover.
- **Perfil de usuário**: `user_display_name`, `user_email`, `user_avatar_path` e `user_theme` são preferências de UI e **permanecem**.
- **Migrations antigas**: não alterar `202607160001_initial_foundation.py`; o drop das tabelas ocorre na Fase 6.
