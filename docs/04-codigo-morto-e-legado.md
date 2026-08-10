# Código Morto e Legado

Código que não é usado pela aplicação (apenas por testes), duplicações com risco de
divergência e resquícios de arquiteturas antigas.

> **Status: ✅ ITENS DE AÇÃO CORRIGIDOS (10/08/2026)**
> Decisões do usuário: remover módulo órfão (4.1) e remover funções mortas (4.6).
> `ruff check app tests` limpo · `mypy app tests` 0 erros · suíte pytest passando.

---

## 4.1 Módulo de autenticação órfão: `app/auth/user_store.py` ✅

**Arquivo:** `app/auth/user_store.py` — **removido** (decisão do usuário).

- Removido o módulo inteiro (segundo sistema de usuários em JSON, formato de hash próprio).
- Removidos de `tests/test_security_regressions.py`: os imports de `user_store`,
  o teste `test_local_user_store_creates_and_verifies_user` e a parte de `users.json`
  do teste `test_runtime_json_corruption_falls_back_safely` (que exercitava
  `verify_user` com arquivo corrompido). O teste mantém a cobertura de corrupção de
  `preferences.json` e `ideas.json`.
- O sistema ativo (PostgreSQL, `app/auth/passwords.py`) permanece intacto — agora há
  **uma única** fonte de verdade para senhas/usuários.

---

## 4.2 Função duplicada: `render_timeline_video_with_audio` ✅

**Arquivo:** `app/finalization/ffmpeg_exporter.py`

- Removida a cópia não utilizada `render_timeline_video_with_audio` (nunca chamada em
  produção) e os imports que ficaram órfãos (`Sequence`, `Any`).
- `finalization/service.py` continua delegando `render_timeline_video` e
  `concat_file_line` ao exporter, e mantém sua cópia privada `_render_timeline_video_with_audio`
  (a usada em produção e coberta por `tests/test_finalization_profile.py`).

---

## 4.3 Código inalcançável em `_approve_video_prompts_from_ui` ✅

**Arquivo:** `app/ui/visual/actions.py`

- Já corrigido na rodada de **bugs críticos** (item 1.8): o bloco morto após
  `ui.navigate.reload(); return` foi removido.

---

## 4.4 Parâmetros de duração não utilizados no Idea Lab ✅

**Arquivo:** `app/storytelling/idea_lab.py`

- Já corrigido na rodada de **bugs funcionais** (item 2.1): `duration_minutes` e
  `target_duration_minutes` agora são usados (prompt, geradores e `_normalize_idea`).

---

## 4.5 Import não utilizado ✅

**Arquivos:** `app/storytelling/normalization.py`, `app/storytelling/story_bible_normalization.py`

- Removido o import `validate_story_bible_payload` de `normalization.py`.
- A função estava 100% sem chamadores — **removida** também de
  `story_bible_normalization.py`, junto com o import de `GenerationOutputError`
  que ficou órfão. `story_bible_validation_errors` e `story_bible_quality_report`
  permanecem (usados por `normalization.py`).

---

## 4.6 Fallback para mock desativado de forma permanente ✅

**Arquivo:** `app/generation/service.py`

- Removidas as funções mortas `should_fallback_to_mock` e `allow_runtime_mock_fallback`
  (decisão do usuário), e os 4 testes que as exercitavam em
  `tests/test_prompt_compiler.py` (inclusive o import).
- A intenção da política ficou **documentada no ponto real de bloqueio**,
  `_generate_with_timeout`: provedores `mock-*` são bloqueados em runtime
  (`raise ValueError("Provider mock bloqueado. Configure um modelo real de IA.")`).
- `should_fallback_to_text_provider` (usada em produção e testada) foi **preservada**.

---

## 4.7 Função com ramos inúteis ✅

- `app/config/settings.py::_optional_provider` — `legacy_default` removido na rodada
  de **bugs funcionais** (item 2.4).
- `app/config/provider_policy.py::provider_requires_api_key` — corrigido na rodada de
  **bugs funcionais** (item 2.5), agora distingue providers reais de mock/desconhecidos.

---

## 4.8 Duplicação de `redact_secrets` ✅

**Arquivos:** `app/observability/redaction.py` (fonte única) e `app/quality/security.py`

- `quality/security.py` agora **importa** `redact_secrets` de `observability/redaction.py`;
  removidas a implementação local e a lista `SECRET_PATTERNS`.
- **Mudança intencional de comportamento:** a versão unificada mantém o nome da chave
  (`api_key=[REDACTED]`) e não exige comprimento mínimo do valor — a detecção fica
  **levemente mais agressiva** no `security_scan_text` (valores curtos do tipo
  `api_key=...` passam a ser sinalizados). Testes de `test_quality_security.py` e
  `test_observability_events.py` passam.

---

## 4.9 Resquícios de Celery/OpenRouter ✅

- `app/ui/page_runtime.py` / `app/ui/shared/assistant_state.py` — a normalização da
  mensagem legada `LEGACY_EXTERNAL_QUEUE_MESSAGE` foi **removida** na rodada de
  **bugs funcionais** (item 2.7, decisão do usuário).
- `.github/workflows/ci.yml` — removidas as variáveis inexistentes no código:
  `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` e `OPENROUTER_API_KEY`.
  `REDIS_URL` foi **mantida** (usada por `settings.redis_url` e pelo health check de
  observabilidade).

---

## 4.10 Re-exports da UI (`app/ui/pages.py`) — sem ação

Falsos positivos do vulture: os símbolos re-exportados com `# noqa: F401` são usados
dinamicamente via `_page_attr`/`getattr(sys.modules["app.ui.pages"], name)` em
`app/ui/page_runtime.py`. Mantidos. A fragilidade do padrão de ponte `getattr` está
documentada em `09-arquitetura-e-divida-tecnica.md`.

---

## 4.11 Outros pontos menores — sem ação

- Providers `mock.py` mantidos (modo smoke/testes) — o bloqueio de runtime está ativo
  em `_generate_with_timeout` (ver 4.6).
- `scripts/*.ps1` — wrappers de compatibilidade, conforme README.
- `SUPPORTED_MODEL_PROVIDERS` — nota de nomenclatura confirmada (sem bug).
