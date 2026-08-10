# Código Morto e Legado

Código que não é usado pela aplicação (apenas por testes), duplicações com risco de
divergência e resquícios de arquiteturas antigas.

---

## 4.1 Módulo de autenticação órfão: `app/auth/user_store.py`

**Arquivo:** `app/auth/user_store.py` — **não é importado por nenhum código de produção**
(apenas por `tests/test_security_regressions.py`).

- Implementa um segundo sistema de usuários baseado em arquivo JSON
  (`.runtime/users.json`) com PBKDF2 de 210.000 iterações e formato próprio de hash.
- O sistema **ativo** usa PostgreSQL (`app/projects/models.User`) com
  `app/auth/passwords.py` (PBKDF2 260.000, formato `pbkdf2_sha256$...`).

**Consequência:** dois formatos de senha e duas fontes de verdade. Alguém que tente
"resolver" autenticação pode mexer no módulo errado.

**Correção sugerida:** remover `user_store.py` e os testes que o exercitam, ou consolidar
em um único sistema.

---

## 4.2 Função duplicada: `render_timeline_video_with_audio`

**Arquivos:** `app/finalization/ffmpeg_exporter.py` (linha 125) e
`app/finalization/service.py` (`_render_timeline_video_with_audio`, linha ~91)

- A versão de `ffmpeg_exporter.py` **nunca é chamada** em produção.
- `finalization/service.py` mantém uma cópia quase idêntica (com `_render_timeline_video`).

**Correção sugerida:** remover a cópia não utilizada ou fazer o `service.py` delegar
integralmente ao `ffmpeg_exporter.py`.

---

## 4.3 Código inalcançável em `_approve_video_prompts_from_ui`

**Arquivo:** `app/ui/visual/actions.py` (linhas ~530-546)

Após `ui.navigate.reload(); return`, existe um bloco morto que referencia `result`, `jobs`,
`clips` (fluxo antigo de geração direta de vídeo, removido em favor da fila de jobs).
O vulture reporta: `app/ui/visual/actions.py:546: unreachable code after 'return'`.

**Correção sugerida:** remover o bloco morto.

---

## 4.4 Parâmetros de duração não utilizados no Idea Lab

**Arquivo:** `app/storytelling/idea_lab.py`

- `idea_lab.py:37` — `duration_minutes` não usado em `build_idea_lab_prompt`.
- `idea_lab.py:108` e `:132` — `target_duration_minutes` não usado.

(Comportamento detalhado em `02-bugs-funcionais.md` item 2.1.)

---

## 4.5 Import não utilizado

**Arquivo:** `app/storytelling/normalization.py:57` — `validate_story_bible_payload`
importado e não usado (provável resquício da remoção do story bible, migração
`202607210012_remove_story_bible.py`).

---

## 4.6 Fallback para mock desativado de forma permanente

**Arquivo:** `app/generation/service.py`

- `should_fallback_to_mock(exc)` (linha 303) — **não é chamado** por código de produção.
- `allow_runtime_mock_fallback(task, requested)` (linha 404) — sempre retorna `False` e
  só é exercitada por `tests/test_prompt_compiler.py:114`.

**Observação:** o bloqueio de mock é intencional (chaves/qualidade), mas as funções ficaram
mortas. Manter apenas o que for de fato usado, ou documentar a intenção.

---

## 4.7 Função com ramos inúteis

- `app/config/settings.py::_optional_provider` — parâmetro `legacy_default` ignorado
  (ver `02-bugs-funcionais.md` item 2.4).
- `app/config/provider_policy.py::provider_requires_api_key` — sempre `True`
  (ver `02-bugs-funcionais.md` item 2.5).

---

## 4.8 Duplicação de `redact_secrets`

**Arquivos:** `app/observability/redaction.py` e `app/quality/security.py`

Duas implementações independentes de `redact_secrets` com padrões diferentes
(uma redige chaves estilo `sk-...`, a outra `api_key=...`). As duas são usadas em
contextos distintos, mas a sobreposição dificulta manter os padrões atualizados.

**Correção sugerida:** unificar em um único módulo (ex.: `observability/redaction.py`) e
importar nos dois lugares.

---

## 4.9 Resquícios de Celery/OpenRouter

- `app/ui/page_runtime.py` — `LEGACY_EXTERNAL_QUEUE_MESSAGE` (mensagem do antigo worker)
  e a normalização correspondente.
- `.github/workflows/ci.yml` — variáveis de ambiente `CELERY_BROKER_URL`,
  `CELERY_RESULT_BACKEND` e `OPENROUTER_API_KEY` que **não existem mais no código**.
- README já documenta: "Não há dependência de Celery ou worker externo".

---

## 4.10 Re-exports da UI (`app/ui/pages.py`) — falsos positivos do vulture

`app/ui/pages.py` re-exporta dezenas de símbolos com `# noqa: F401` para que
`app/ui/page_runtime.py` os acesse via `getattr(sys.modules["app.ui.pages"], name)`
(`_page_attr`). O vulture os marca como código morto, mas **são usados dinamicamente**.

**Atenção:** esse padrão de "ponte" via `getattr` é frágil — qualquer renomeação quebra em
runtime sem erro estático (ver `09-arquitetura-e-divida-tecnica.md`).

---

## 4.11 Outros pontos menores

- `app/providers/llm/mock.py`, `image/mock.py`, `video/mock.py`, `speech/mock.py` — usados
  apenas por testes/modos smoke. OK manter, mas confirmar que o bloqueio de runtime está
  ativo (está — `validate_model_name` bloqueia `mock-*`).
- `scripts/app.ps1`, `scripts/executar.ps1`, `scripts/finalizar.ps1` — wrappers de
  compatibilidade, conforme README.
- `app/generation/model_settings.py::SUPPORTED_MODEL_PROVIDERS` é
  `frozenset(SUPPORTED_TEXT_PROVIDERS)` = `{"ollama_cloud"}` — o campo `provider` de
  `ProjectModelSetting` só aceita um provider hoje; o restante do código trata
  `google_ai`/`elevenlabs` como providers de mídia, então não há bug, mas a nomenclatura
  confunde.
