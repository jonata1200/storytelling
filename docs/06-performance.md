# Performance

Pontos onde a aplicação faz trabalho desnecessário, bloqueia o event loop ou gera N+1.
Para uma aplicação local single-user o impacto é limitado, mas alguns itens ficam
lentos em projetos grandes.

---

## 6.1 Laço duplicado e N+1 na geração de vídeo

**Arquivo:** `app/video_generation/service.py` (`_generate_video_clips_concurrent`)

- Os frames são percorridos **duas vezes** com as mesmas queries de idempotência
  (ver `01-bugs-criticos.md` item 1.4).
- `_asset_storage_uri(session, frame.asset_id)` faz um `session.get(Asset)` **por frame**
  (`service.py` ~linha 219); com dezenas de frames são dezenas de round-trips ao banco.

**Correção sugerida:** buscar todos os assets em uma única query
(`select(Asset).where(Asset.id.in_(...))`) e unificar os laços.

---

## 6.2 Commit + read-modify-write de metadata a cada tick de progresso

**Arquivo:** `app/jobs/service.py` (`_set_project_job_action`, linhas ~83-107)

A cada chamada de `mark_job_running`/`mark_job_progress`/`mark_job_succeeded`/`mark_job_failed`:

1. `get_or_create_production_settings(session, project_id)` — busca/insere settings;
2. lê `metadata_json` inteiro, adiciona um evento, grava de novo;
3. `await session.commit()`.

Com polls de progresso a cada poucos segundos e eventos acumulados
(`events[-60:]`), o metadata cresce e cada commit reescreve tudo. Em projetos grandes com
várias etapas, o `production_settings.metadata_json` pode ficar grande.

**Correção sugerida:** persistir `ai_action`/eventos em tabela própria ou gravar apenas o
evento incremental; pelo menos evitar o commit por tick desnecessário.

---

## 6.3 `iter_local_storage_files` varre todo o storage

**Arquivo:** `app/storage/service.py` (`iter_local_storage_files`, linha ~76)

`rglob("*")` percorre **todos os arquivos** do storage (que pode ter GBs de vídeos) a cada
chamada de uso/limpeza/reconciliação. Para a tela de Storage com muitos projetos isso pode
levar segundos.

**Correção sugerida:** cachear os metadados (tamanho/mtime) na tabela `assets` (já existe
`size_bytes`, `storage_checked_at`) e evitar o scan completo, ou limitar o scan ao
diretório do projeto quando `project_id` é informado.

---

## 6.4 Consultas repetidas nas telas da UI

**Arquivo:** `app/ui/project/data.py` (`project_summary` etc.)

A montagem do workspace consulta o banco dezenas de vezes por página (contagens por modelo,
último artefato de cada tipo, jobs, frames, clipes). Para uso local é aceitável; para
muitos projetos a tela inicial (`home_pages.py`, `project_cards`) também faz uma query por
card.

**Correção sugerida:** montar 2-3 queries agregadas por página (ex.: um `select` com
`count(*) group by artifact_type`) em vez de uma por seção.

---

## 6.5 Polling da UI a cada 2-5 segundos

**Arquivos:** `app/ui/workspace/script_area.py`, `app/ui/pages.py`

`ui.timer(2.0, ...)`/`ui.timer(5.0, ...)` consultam o banco (via `_script_generation_progress_state`)
repetidamente enquanto um job roda. É o mecanismo de progresso escolhido (sem websocket de
eventos), mas gera tráfego constante de banco durante gerações longas.

**Correção sugerida:** usar os eventos de observabilidade (`operational_events`) já emitidos
por `emit_project_event` para alimentar o progresso, ou aumentar o intervalo e usar
backoff.

---

## 6.6 FFmpeg e providers — já tratados corretamente (sem ação)

- `app/finalization/service.py:722` usa `asyncio.to_thread` para a renderização FFmpeg.
- `app/providers/*` usam `asyncio.to_thread` para chamadas HTTP síncronas (`urllib`).

Esses pontos **não bloqueiam o event loop** — estão corretos.

---

## 6.7 Geração de storyboard em paralelo

**Arquivo:** `app/storyboards/frame_generation.py:202`

`asyncio.gather` para planos — com `storyboard_image_concurrency=3` como teto (semântica OK).
Sem ação, apenas confirmação de que o teto global de concorrência de vídeo
(`video_generation_concurrency`) é respeitado em `video_generation/service.py` (está).
