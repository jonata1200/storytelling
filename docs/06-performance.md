# Performance

Pontos onde a aplicação faz trabalho desnecessário, bloqueia o event loop ou gera N+1.
Para uma aplicação local single-user o impacto é limitado, mas alguns itens ficam
lentos em projetos grandes.

> **Status: 5/5 itens acionáveis corrigidos** (06/08/2026) — 6.6 e 6.7 eram "sem ação" (confirmado).

---

## 6.1 Laço duplicado e N+1 na geração de vídeo ✅

**Arquivo:** `app/video_generation/service.py` (`_generate_video_clips_concurrent`)

- Os frames são percorridos **duas vezes** com as mesmas queries de idempotência
  (ver `01-bugs-criticos.md` item 1.4).
- `_asset_storage_uri(session, frame.asset_id)` faz um `session.get(Asset)` **por frame**
  (`service.py` ~linha 219); com dezenas de frames são dezenas de round-trips ao banco.

**Correção sugerida:** buscar todos os assets em uma única query
(`select(Asset).where(Asset.id.in_(...))`) e unificar os laços.

**Aplicado:**
- ✅ Todos os assets dos frames são carregados em **uma única query** antes do laço
  (`select(Asset).where(Asset.id.in_(frame_asset_ids))`) e resolvidos via
  `assets_by_id` — elimina o N+1 (dezenas de `session.get` → 1 round-trip).
- ✅ O helper `_asset_storage_uri` (agora sem chamadores) foi **removido**.
- O laço duplicado (planejamento + execução) é estrutural e foi mantido — as queries
  de idempotência dentro dele são necessárias para a lógica de retomada/retry.

---

## 6.2 Commit + read-modify-write de metadata a cada tick de progresso ✅

**Arquivo:** `app/jobs/service.py` (`_set_project_job_action`, linhas ~83-107)

A cada chamada de `mark_job_running`/`mark_job_progress`/`mark_job_succeeded`/`mark_job_failed`:

1. `get_or_create_production_settings(session, project_id)` — busca/insere settings;
2. lê `metadata_json` inteiro, adiciona um evento, grava de novo;
3. `await session.commit()`.

**Aplicado:**
- ✅ **Cache de settings por execução de job**: `get_or_create_production_settings` é
  chamado uma única vez por job (atributo transiente `_project_action_settings`, mesmo
  padrão do `_should_dispatch_after_enqueue`). Comentário documenta a invariante
  "uma sessão por ciclo de vida do job" (o runner recarrega o job em sessão nova).
- ✅ **Dedupe de eventos idênticos consecutivos**: se `(status, message, error)` for
  igual ao último evento escrito, o histórico **não** ganha um evento duplicado e o
  `events[-60:]` não cresce à toa. Para não quebrar o timeout da UI
  (`_ai_action_exceeded_generation_timeout`), o `updated_at` do `ai_action` é
  **refreshed** nesse caminho (flush leve, sem append).
- O `commit` por tick continua existindo porque persiste `job.progress` para o polling
  da UI — removê-lo quebraria o progresso; a redução de trabalho por tick é a parte
  que importa.

---

## 6.3 `iter_local_storage_files` varre todo o storage ✅

**Arquivo:** `app/storage/service.py` (`iter_local_storage_files`, linha ~76)

`rglob("*")` percorre **todos os arquivos** do storage (que pode ter GBs de vídeos) a cada
chamada de uso/limpeza/reconciliação. Para a tela de Storage com muitos projetos isso pode
levar segundos.

**Aplicado:**
- ✅ `list_orphan_storage_files`/`cleanup_orphan_storage_files` agora escaneiam **apenas
  os diretórios do projeto** quando `project_id` é informado (`_project_scan_dirs` →
  `root/<tipo>/<project_id>`), em vez do `rglob` na raiz inteira. Sem `project_id`, o
  scan completo continua (ação administrativa explícita).
- ⚠️ Comportamento para layouts não padronizados: arquivos cujo caminho contém o
  project_id mas **fora** de `root/<tipo>/<project_id>` (ex.: `root/backup-<id>/`) deixam
  de ser listados no filtro por projeto. O layout padrão da aplicação é
  `root/<tipo>/<project_id>` (visual, storyboard, vídeo, dubbing, dialogue, exports,
  animatics, uploaded_references), então o caso é aceitável — documentado.
- ✅ Testes novos: `test_list_orphan_storage_files_scopes_scan_to_project_directory`
  (verifica que o scan usa o diretório do projeto) e
  `test_list_orphan_storage_files_finds_project_orphans_without_global_scan`.
  *O teste pegou um bug na implementação inicial do helper (retornava o diretório do
  tipo em vez do do projeto) — corrigido.*

---

## 6.4 Consultas repetidas nas telas da UI ✅

**Arquivo:** `app/ui/project/data.py` (`project_summary` etc.)

A montagem do workspace consulta o banco dezenas de vezes por página (contagens por modelo,
último artefato de cada tipo, jobs, frames, clipes). Para uso local é aceitável; para
muitos projetos a tela inicial (`home_pages.py`, `project_cards`) também faz uma query por
card.

**Aplicado:**
- ✅ **`project_summary`**: as **16 contagens** do workspace (8 `count` simples por
  project_id, 7 `count` com join em `Artifact` filtrando status ativos, e
  `stale_artifacts`) agora saem de **uma única query** `UNION ALL`
  (`project_counts_statement`), em vez de 16 round-trips.
- ✅ **`dashboard_metrics`** (tela inicial): 5 contagens → **1 query** `UNION ALL`
  (`dashboard_metrics_statement`).
- ✅ Builders separados dos executores (`*_statement`) para permitir teste sem banco.
- ✅ `active_count` (sem chamadores restantes) **removido**; `scalar_count` mantido
  (ainda usado por `pages.py`).
- ✅ Testes de compilação novos (`tests/test_ui_project_data.py`): os statements compilam
  em SQLite e PostgreSQL e produzem o número esperado de `UNION ALL` (15 no workspace,
  4 no dashboard).
- ℹ️ Não foi possível um teste com DB real (semântica das linhas): o driver `aiosqlite`
  não está instalado e o banco é PostgreSQL. O padrão `UNION ALL` de
  `(literal, count)` é padrão SQLAlchemy e espelha exatamente as queries antigas.
  **Opcional (decisão sua):** adicionar `aiosqlite` como dependência de dev para um
  teste de integração real das contagens.

---

## 6.5 Polling da UI a cada 2-5 segundos ✅

**Arquivos:** `app/ui/workspace/script_area.py`, `app/ui/pages.py`

`ui.timer(2.0, ...)`/`ui.timer(5.0, ...)` consultam o banco (via `_script_generation_progress_state`)
repetidamente enquanto um job roda. É o mecanismo de progresso escolhido (sem websocket de
eventos), mas gera tráfego constante de banco durante gerações longas.

**Aplicado:**
- ✅ **Backoff progressivo**: novo helper compartilhado `script_progress_poll_interval`
  (`app/ui/shared/page_config.py`) com a sequência `2.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0` s.
  Os callbacks de progresso (`_update_script_generation_progress` e
  `_close_loading_dialog_when_script_ready`) agora **se reagendam** com `ui.timer(..., once=True)`
  e intervalo crescente, em vez de um timer fixo batendo para sempre.
- ✅ **Correção importante (da revisão de código)**: os 3 call sites usavam timer
  **repetitivo** enquanto o callback se reagendava — cada tick criaria uma nova cadeia de
  timers (acúmulo). Todos agora usam `once=True`, deixando o self-reschedule como único
  mecanismo de polling.
- ✅ `fake_timer` dos testes de UI atualizado para aceitar `once`.

---

## 6.6 FFmpeg e providers — já tratados corretamente (sem ação) ✅

- `app/finalization/service.py:722` usa `asyncio.to_thread` para a renderização FFmpeg.
- `app/providers/*` usam `asyncio.to_thread` para chamadas HTTP síncronas (`urllib`).

Esses pontos **não bloqueiam o event loop** — estão corretos. (Confirmado, sem ação.)

---

## 6.7 Geração de storyboard em paralelo (sem ação) ✅

**Arquivo:** `app/storyboards/frame_generation.py:202`

`asyncio.gather` para planos — com `storyboard_image_concurrency=3` como teto (semântica OK).
Sem ação, apenas confirmação de que o teto global de concorrência de vídeo
(`video_generation_concurrency`) é respeitado em `video_generation/service.py` (está).
(Confirmado, sem ação.)

---

## Validação

- **Ruff**: `All checks passed!` ✅
- **Mypy app tests**: `Success: no issues found in 280 source files` ✅
- **Pytest** (suíte completa): ✅ passando (1 skip esperado) — inclui 6 testes novos
  (2 do storage, 1 do jobs, 4 de compilação de statements da UI)
- Revisão de código (code-reviewer): pontos apontados na 1ª rodada **todos resolvidos**
  (acúmulo de timers, `updated_at` congelado no dedupe, invariante de sessão do cache).
