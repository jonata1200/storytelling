# Revisão de Segurança

Pontos fortes e fragilidades identificados na revisão manual dos módulos de auth, upload,
storage e providers.

---

## 5.1 Pontos fortes (o que está correto)

- **Cookies de sessão:** `HttpOnly=True`, `SameSite=Lax`, `Secure` fora de
  local/development/test (`app/auth/ui_routes.py`).
- **CSRF:** token em cookie + formulário, assinado com HMAC do `APP_SECRET_KEY`
  (`app/auth/csrf.py`); validado em login/registro (desativado apenas em local/test, por
  design).
- **Senhas:** PBKDF2-HMAC-SHA256 com 260.000 iterações e salt por usuário
  (`app/auth/passwords.py`).
- **Rate limit:** 8 tentativas/60s por host+email em memória (`ui_routes.py`).
- **Sessões persistentes:** token aleatório armazenado com **hash SHA-256** no banco,
  com revogação e expiração (`app/auth/session.py`).
- **Bypass de auth** restrito a `APP_ENV=local|test` (`app/auth/dependencies.py`), com
  validação que **rejeita** `APP_SECRET_KEY`/`APP_DEBUG` inseguros fora de ambientes locais
  (`app/config/settings.py::reject_insecure_non_local_defaults`).
- **Redação de segredos** em logs e mensagens de erro dos providers
  (`app/observability/redaction.py`).
- **Escaneamento de injeção de prompt** em briefing e roteiro
  (`app/quality/security.py`, usado em `app/quality/service.py`).
- **Traversal de caminho:** `resolve_storage_path` valida que o arquivo fica dentro do
  storage root (`app/storage/service.py`), e `_local_video_asset_path`
  (`finalization/service.py`) também restringe.
- **Uploads:** validação de extensão e tamanho (script 10 MB; referência 10 MB; avatar
  5 MB).

---

## 5.2 Fragilidades e recomendações

### 5.2.1 `APP_SECRET_KEY` padrão em ambientes locais

`app/config/settings.py` usa default `change-me-in-development`. Em `APP_ENV=local` não há
validação. O `APP_SECRET_KEY` assina tokens de sessão estateless
(`verify_session_token`) e CSRF — se o deploy local subir com o default, qualquer pessoa
com acesso à rede pode **forjar tokens válidos** (o valor é público no repositório).

**Recomendação:** gerar um segredo aleatório automaticamente no primeiro boot
(se ainda for o default e `APP_ENV=local`), ou ao menos exibir um aviso na UI/console.

### 5.2.2 Token de sessão "stateless" legado sem revogação

`app/auth/session.py::verify_session_token` — tokens HMAC com payload
`username:expires_at` não têm revogação no servidor e são aceitos até expirar (7 dias).
O logout só revoga a sessão **persistente** (`UserSession`).

**Recomendação:** descontinuar o token stateless (mantido só por compatibilidade) e aceitar
apenas sessões persistentes.

### 5.2.3 Auth completamente desligada em local/test

`require_authenticated_user` retorna `"local-user"` sem verificar nada quando
`APP_ENV ∈ {local, test}`. Isso é documentado e aceitável para uso local, mas **qualquer
máquina na rede pode acessar a aplicação sem senha** se ela subir com `APP_ENV=local`
(não é o caso do compose/script, que usam local — avaliar risco no seu ambiente).

### 5.2.4 Validação de uploads apenas por extensão

`reference_upload.py`, `script_upload.py` e o avatar em `settings_page.py` validam a
**extensão do nome do arquivo**, mas não conferem "magic bytes". Um `.png` com payload
HTML/JS é aceito e servido por `/storage` (montado em local/test) com o Content-Type
derivado da extensão. Para uso local o risco é baixo, mas convém validar o cabeçalho real
do arquivo.

### 5.2.5 `document.xml` de DOCX sem limite de tamanho descomprimido

`app/storytelling/script_upload.py::_extract_docx_text` lê `word/document.xml`,
`footnotes.xml` e `endnotes.xml` e os junta sem limitar o tamanho descomprimido — um DOCX
"zip bomb" pode inflar o uso de memória (o limite de 10 MB é sobre o arquivo compactado).

**Recomendação:** limitar o tamanho total do texto extraído (ex.: 1-2 MB) e abortar acima
disso.

### 5.2.6 Arquivos-fonte da UI servidos publicamente

`app/factory.py` monta `/ui-assets` apontando para o diretório `app/ui` — que contém
**arquivos `.py`**. Em qualquer ambiente, `/ui-assets/*.py` é baixável sem autenticação
(pequeno vazamento de implementação). Em local/test, `/storage` também é público.

**Recomendação:** servir apenas `app/ui/static` (ou um subdiretório de assets), não o
pacote inteiro.

### 5.2.7 Chaves de API em texto puro em `.runtime/preferences.json`

`save_runtime_preferences` grava as chaves (`OLLAMA_CLOUD_API_KEY`, etc.) em JSON em disco.
O diretório `.runtime/` é gitignored (bom), mas o arquivo não tem permissões restritas.

**Recomendação:** aplicar permissões `0600` ao arquivo de preferências.

### 5.2.8 Rate limit em memória sem limpeza

`_AUTH_ATTEMPTS` (`ui_routes.py`) acumula chaves `host:email` sem expiração — crescimento
lento, irrelevante para uso local, mas digno de nota se a aplicação for exposta.

### 5.2.9 Código de teste exercitando módulo morto

`tests/test_security_regressions.py` valida `user_store.py` (módulo morto — ver
`04-codigo-morto-e-legado.md`). Isso cria **falsa sensação de cobertura** de autenticação:
o sistema de senha realmente usado (PostgreSQL) tem cobertura menor.

---

## 5.3 Checklist rápido

- [ ] Trocar `APP_SECRET_KEY` real no `.env` (não usar o default).
- [ ] Avaliar se `APP_ENV=local` com auth desligada é aceitável na sua rede.
- [ ] Validar magic bytes em uploads de imagem/PDF.
- [ ] Limitar texto extraído de DOCX.
- [ ] Restringir `/ui-assets` a assets estáticos.
- [ ] Chmod 0600 em `.runtime/preferences.json` e `.runtime/users.json`.
- [ ] Unificar `redact_secrets` (duplicado entre `observability/redaction.py` e
      `quality/security.py`).
