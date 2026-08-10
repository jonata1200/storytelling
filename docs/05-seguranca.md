# Revisão de Segurança

Pontos fortes e fragilidades identificados na revisão manual dos módulos de auth, upload,
storage e providers.

> **Status: ✅ FRAGILIDADES CORRIGIDAS (10/08/2026)**
> Decisões do usuário: aviso no lugar de auto-geração de segredo (5.2.1) e remoção do
> token stateless (5.2.2). `ruff check app tests` limpo · `mypy app tests` 0 erros ·
> suíte pytest passando.

---

## 5.1 Pontos fortes (o que está correto)

Sem mudanças — itens confirmados:

- **Cookies de sessão:** `HttpOnly=True`, `SameSite=Lax`, `Secure` fora de
  local/development/test (`app/auth/ui_routes.py`).
- **CSRF:** token em cookie + formulário, assinado com HMAC do `APP_SECRET_KEY`
  (`app/auth/csrf.py`); validado em login/registro (desativado apenas em local/test).
- **Senhas:** PBKDF2-HMAC-SHA256 com 260.000 iterações e salt por usuário
  (`app/auth/passwords.py`).
- **Rate limit:** 8 tentativas/60s por host+email em memória (`ui_routes.py`), agora com
  limpeza de chaves expiradas (ver 5.2.8).
- **Sessões persistentes:** token aleatório armazenado com **hash SHA-256** no banco,
  com revogação e expiração (`app/auth/session.py`). **Único** mecanismo de sessão ativo
  (ver 5.2.2).
- **Bypass de auth** restrito a `APP_ENV=local|test` (`app/auth/dependencies.py`), com
  validação que **rejeita** `APP_SECRET_KEY`/`APP_DEBUG` inseguros fora de ambientes locais
  (`app/config/settings.py::reject_insecure_non_local_defaults`).
- **Redação de segredos** em logs e mensagens de erro dos providers
  (`app/observability/redaction.py`), unificada (ver 04/4.8).
- **Escaneamento de injeção de prompt** em briefing e roteiro
  (`app/quality/security.py`, usado em `app/quality/service.py`).
- **Traversal de caminho:** `resolve_storage_path` valida que o arquivo fica dentro do
  storage root (`app/storage/service.py`), e `_local_video_asset_path`
  (`finalization/service.py`) também restringe.
- **Uploads:** validação de extensão, tamanho **e magic bytes** (ver 5.2.4).

---

## 5.2 Fragilidades e recomendações

### 5.2.1 `APP_SECRET_KEY` padrão em ambientes locais ✅

`app/config/settings.py` usa default `change-me-in-development` (agora a constante
`DEFAULT_APP_SECRET_KEY`). Em `APP_ENV=local` não há validação.

**Correção aplicada (decisão do usuário: aviso):**
- Nova função `insecure_default_secret_key_warning()` em `settings.py` — retorna a
  mensagem de alerta quando o segredo ainda é o default.
- **Console:** `factory.py` loga `logger.warning(...)` no startup.
- **UI:** banner âmbar na página Configurações (`settings_page.py`) com o aviso.

### 5.2.2 Token de sessão "stateless" legado sem revogação ✅

**Correção aplicada (decisão do usuário: remover):** o mecanismo stateless
(`create_session_token`/`verify_session_token`, HMAC `username:expires_at` sem revogação)
foi **removido**. Agora a aplicação aceita **apenas sessões persistentes** revogáveis
(`UserSession` no banco):
- `app/auth/session.py` — funções stateless removidas (e `import time` órfão).
- `app/auth/dependencies.py` e `app/auth/ui_middleware.py` — fallback stateless removido.
- `tests/test_auth.py` — teste do middleware reescrito com monkeypatch de
  `verify_persistent_session_token`.
- Efeito: cookies emitidos por versões antigas (máx. 7 dias) deixam de autenticar; o
  usuário refaz o login uma vez e recebe uma sessão persistente.

### 5.2.3 Auth completamente desligada em local/test — sem ação (documentado)

`require_authenticated_user` retorna `"local-user"` sem verificar nada quando
`APP_ENV ∈ {local, test}`. Comportamento documentado e aceitável para uso local; avaliar o
risco de exposição na rede ao subir com `APP_ENV=local` (não é o caso do compose/script).

### 5.2.4 Validação de uploads apenas por extensão ✅

**Correção aplicada:** validação de **magic bytes** adicionada:
- `app/providers/media_utils.py` — novos helpers compartilhados
  `image_signature_matches` (PNG/JPEG/WEBP), `pdf_signature_matches` (`%PDF-`) e
  `docx_signature_matches` (`PK\x03\x04`).
- `app/storytelling/reference_upload.py` — `prepare_reference_upload` rejeita conteúdo
  que não corresponde à extensão.
- `app/storytelling/script_upload.py` — rejeita PDF/DOCX com assinatura incorreta.
- Avatar: `app/ui/layout/navigation.py::save_avatar_file` valida a assinatura e
  `settings_page.py` exibe notificação de erro (`try/except ValueError`).
- Testes atualizados com bytes reais de assinatura + novos testes de rejeição.

### 5.2.5 `document.xml` de DOCX sem limite de tamanho descomprimido ✅

**Correção aplicada** em `app/storytelling/script_upload.py`:
- `_read_zip_member_capped` lê cada membro (document/footnotes/endnotes) em chunks de
  64 KB com **teto de 5 MB por membro** (mitigação real de zip bomb via `archive.open()`).
- Limite de **2 milhões de caracteres** para o texto total extraído.
- Exceder qualquer limite aborta com `ScriptUploadError` descritivo.
- Teste `test_docx_member_read_is_capped_against_zip_bomb` cobre o cap.

### 5.2.6 Arquivos-fonte da UI servidos publicamente ✅

**Correção aplicada:** `/ui-assets` agora aponta apenas para `app/ui/static`
(`factory.py`), que contém somente o `favicon.png` (movido com `git mv`). Os arquivos
`.py` do pacote `app/ui` **não são mais baixáveis**. Referências
(`/ui-assets/favicon.png`) permanecem válidas.

### 5.2.7 Chaves de API em texto puro em `.runtime/preferences.json` ✅

**Correção aplicada** em `app/config/runtime_preferences.py`: `os.chmod(path, 0o600)`
após a gravação (o `mkstemp` já usa 0600 no POSIX; o chmod explícito é defensivo e
documentado). `.runtime/` continua gitignored.

### 5.2.8 Rate limit em memória sem limpeza ✅

**Correção aplicada** em `app/auth/ui_routes.py`: nova função
`_prune_stale_auth_attempts` remove chaves `host:email` sem atividade nos últimos 60s,
acionada quando o dicionário passa de 500 chaves. Teste adicionado
(`test_auth_rate_limit_prunes_stale_attempt_keys`).

### 5.2.9 Código de teste exercitando módulo morto ✅

Resolvido na rodada de **código morto** (04/4.1): `user_store.py` removido e os testes
que o exercitavam eliminados. O sistema de senha real (PostgreSQL) segue coberto por
`test_auth.py`/`test_security_regressions.py`.

---

## 5.3 Checklist rápido

- [ ] **Usuário:** trocar `APP_SECRET_KEY` real no `.env` (não usar o default) — o app
      agora avisa no console e nas Configurações enquanto o default estiver ativo.
- [ ] **Usuário:** avaliar se `APP_ENV=local` com auth desligada é aceitável na sua rede.
- [x] Validar magic bytes em uploads de imagem/PDF (5.2.4).
- [x] Limitar texto extraído de DOCX (5.2.5).
- [x] Restringir `/ui-assets` a assets estáticos (5.2.6).
- [x] Chmod 0600 em `.runtime/preferences.json` (5.2.7) — `.runtime/users.json` não
      existe mais (módulo removido em 04/4.1).
- [x] Unificar `redact_secrets` (04/4.8).
