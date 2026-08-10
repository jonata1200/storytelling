# Arquitetura e Dívida Técnica

> Status: **revisado em 10/08/2026** — itens da prioridade do relatório corrigidos; os
> demais foram verificados (já resolvidos em rodadas anteriores) ou documentados como
> trabalho futuro.

---

## 9.1 Dois sistemas de autenticação

**Status: ✅ JÁ RESOLVIDO** (rodada `04-codigo-morto-e-legado.md`)

`app/auth/` não contém mais `user_store.py` — apenas o sistema PostgreSQL
(`service.py`, `passwords.py`, `session.py`, `ui_middleware.py`, `csrf.py`).

## 9.2 Ponte UI frágil via `getattr` em módulo

**Status: ✅ RESOLVIDO**

`app/ui/page_runtime.py` — a ponte `_page_attr` (`getattr(sys.modules[...], name)`) foi
**eliminada**:

- Novo `_PagesFacade` (Protocol tipado) descreve o módulo `app.ui.pages`; renomes de
  símbolos agora quebram em tempo de análise, não em runtime.
- `register_ui_pages(pages: _PagesFacade)` recebe o **módulo pages** diretamente
  (`factory.py` passa `ui_pages`); o wiring usa atributos (`pages._body_style`, etc.) e
  as funções do próprio runtime são passadas por referência direta.
- Helpers (`_notify_ai_action_failure_once`, `_sync_ai_action_events_to_chat`, `_asset_url`,
  `_render_*_area`) leem o módulo via `_ui_pages()`, com **resolução lazy** (sem dependência
  de ordem de execução nos testes — import em tempo de chamada evita circular import).
- `# noqa: F401` dos re-exports em `pages.py` foram mantidos (são a superfície pública do
  módulo consumida por factory e outros módulos).

## 9.3 Commit espalhado nos routers

**Status: ✅ RESOLVIDO**

- `storage/service.reconcile_local_storage` e `approvals/service.record_approval` agora
  fazem o `commit`; removidos os commits redundantes de `storage/router.py` (2 endpoints),
  `projects/router.py` (`post_artifact_approval`) e o caller `visual_bible/service.py`.
- Padrão "services fazem commit" restaurado; o caminho de erro 409 do approval continua
  sem commit (o `ValueError` é levantado antes).

## 9.4 Execução de jobs dentro do processo

**Status: ✅ RECUPERAÇÃO FEITA; separação de modelos documentada como futuro**

- Recuperação de PENDING/RUNNING no startup implementada (`schedule_stale_job_recovery`
  registrada no `factory.py`) e testada (ver `docs/08` item 8.4.3).
- Migração para worker externo (ARQ/RQ/Celery) e separação do modelo
  "project step" vs "media job": **trabalho futuro** (mudança de arquitetura grande).

## 9.5 Hack de atributo dinâmico em modelo SQLAlchemy

**Status: ✅ RESOLVIDO**

`cast(Any, job)._should_dispatch_after_enqueue` removido. `create_or_resume_project_job`
agora retorna a dataclass **`JobEnqueueDecision(job, should_dispatch)`** (frozen), e
`enqueue_project_step` a desempacota. Sem atributos mágicos perdidos em re-leituras.

## 9.6 Duplicações de código

**Status: ✅ JÁ RESOLVIDO** (rodadas `04` e `05`)

- `redact_secrets` existe apenas em `observability/redaction.py` (o duplicado em
  `quality/security.py` foi removido).
- `render_timeline_video_with_audio` existe apenas em `finalization/service.py` (o do
  `ffmpeg_exporter.py` foi removido).
- O laço duplicado de vídeo foi unificado na rodada de performance (`docs/06`, item 6.1).

## 9.7 Arquivos monolíticos

**Status: ⏳ TRABALHO FUTURO (documentado)**

Extrações por responsabilidade (`video_generation/executor.py`, `finalization/render.py`,
etc.) devem ocorrer **à medida que os arquivos forem alterados**, como recomenda o relatório.

## 9.8 Nomes mágicos de etapas

**Status: ✅ RESOLVIDO (escopo principal)**

Novo **`ProjectStep`** (`StrEnum`) em `app/core/enums.py` com os 10 passos do pipeline.
Usado como fonte única em:

- `jobs/service.py`: `PROJECT_STEP_JOB_TYPES` chaveado por `ProjectStep` e
  `normalize_step` retorna `ProjectStep`.
- `jobs/runner.py`: dispatch `if step == ProjectStep.SCRIPT:` etc.
- Payloads guardam `step.value` (string) — sem impacto em persistência/JSON.

`api_keys.CREATION_STEPS` mantém strings (incluem sub-etapas além do pipeline:
`generate_ideas`, `revise_script`, etc.) — extensão do enum para esses casos fica como
trabalho futuro.

## 9.9 Configuração de providers redundante

**Status: ✅ PARCIALMENTE RESOLVIDO / FUTURO**

- `provider_requires_api_key` já não retorna sempre `True` (retorna `False` para mocks).
- `_optional_provider` permanece como normalizador real das variáveis de provider.
- A simplificação para tabela única canal→provider→modelo por projeto já existe em parte
  (`project_model_settings`/`production_settings`); consolidar os defaults legados é
  **trabalho futuro**.

## 9.10 Tipagem dos modelos (`Base` sem `id`)

**Status: ✅ JÁ RESOLVIDO (mypy verde)**

Os erros `"Base" has no attribute "id"` foram corrigidos na rodada `03` (mypy passa nos
280 arquivos). O Protocol sugerido é um refinamento opcional futuro.

## 9.11 Config em arquivo JSON em vez de banco

**Status: ✅ DOCUMENTADO**

`app/config/runtime_preferences.py` ganhou comentário no topo documentando a limitação:
JSON em disco + cache em memória é suficiente para **processo único**; não sincroniza
entre múltiplos processos — migrar para o banco se a aplicação evoluir para multi-worker.

## 9.12 NiceGUI: upgrade 1.4 → 3.14

**Status: ✅ JÁ RESOLVIDO** (rodada `07`, item 7.5) — piso `nicegui>=3.14.0` no pyproject.

---

## Resumo da rodada

- **6 itens corrigidos** (9.2, 9.3, 9.5, 9.8, 9.11 + 9.9 parcial), **5 já resolvidos em
  rodadas anteriores** (9.1, 9.4-recuperação, 9.6, 9.10, 9.12), **2 documentados como
  futuro** (9.7, 9.4-migração, 9.9-consolidação).
- Validação: **ruff** ✅ · **mypy** (280 arquivos) ✅ · **pytest** completo ✅ (1 skip).
- Revisor pegou 1 problema real (dependência de ordem nos testes por causa do módulo
  global `_pages`) — corrigido com resolução lazy; 2 testes que rodavam em isolamento
  voltaram a passar.
