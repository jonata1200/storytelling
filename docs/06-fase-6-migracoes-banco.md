# Fase 6 — Migrações de banco de dados (drops)

## Objetivo

Executar a decisão D1: remover do banco as tabelas e colunas que ficaram órfãs após as fases 2–5, via migrações Alembic novas. As migrações antigas não são alteradas.

> ⚠️ **Executar somente depois das fases 2–5** (código já não referencia o que será dropado) e **após o backup** sugerido na Fase 1.

## Itens a remover

| Tipo | Item | Origem |
|------|------|--------|
| Tabela | `users` | Fase 2 |
| Tabela | `user_sessions` | Fase 2 |
| Coluna | `workspaces.owner_user_id` (e FK) | Fase 2 |
| Coluna | `approvals.reviewer_user_id` (e FK) | Fase 2 |
| Coluna | `clip_reviews.reviewer_user_id` (e FK) | Fase 2 |
| Tabela | `dubbing_jobs` | Fase 3 |
| Tabela | `exports` | Fase 4 |
| Tabela | `subtitle_tracks` | Fase 4 |
| Tabela | `quality_checks` | Fase 5 |
| Tabela | `continuity_states` | Fase 5 |
| Tabela | `continuity_issues` | Fase 5 |
| Enum | valores `project_status` órfãos: `VIDEO_REVIEW`, `AUDIO_GENERATION`, `ASSEMBLY`, `QUALITY_CONTROL`, `FINAL_APPROVAL` | Fase 5 |

## Checklist de ações

- [x] Gerar **uma única** migração consolidada: `alembic/versions/202608130026_remove_orphan_tables_and_enum_values.py` (revises `202608110025`).
- [x] Na migração, para cada tabela/coluna da lista acima:
      - [x] Remover FKs/índices associados antes do drop (índices explícitos; FKs são derrubadas junto com a coluna pelo PostgreSQL — confirmado na execução).
      - [x] `op.drop_table(...)` / `op.drop_column(...)` — ordem: `dubbing_jobs` → `exports` → `subtitle_tracks`; `quality_checks` → `continuity_issues` → `continuity_states`; `user_sessions` → colunas user FKs → `users`.
- [x] Tratar o enum `project_status`:
      - [x] Antes de remover valores, atualizar linhas existentes que usam valores órfãos para `COMPLETED`.
      - [x] Remover os valores do tipo ENUM — **`ALTER TYPE ... DROP VALUE` NÃO existe no PostgreSQL** (confirmado na execução, mesmo no PG 16): foi usado o approach de **recriar o tipo** (`RENAME` → `CREATE TYPE` com os valores finais → `ALTER COLUMN ... USING col::text::type` → `DROP TYPE legacy`).
      - [x] Conferir os demais enums: `generation_job_type` (removido `RENDER`, mantido `SPEECH`), `artifact_type` (removido `EXPORT`, mantido `TIMELINE`) e `clip_review_decision` (nenhuma mudança — revisão de clipes permanece).
- [x] `alembic/env.py`: imports de `finalization`/`quality`/`dubbing` já removidos nas fases anteriores (confirmado); `app.projects.models` não expõe mais `User`/`UserSession`.
- [x] Rodar `uv run alembic upgrade head` contra o banco de desenvolvimento (PostgreSQL 16 via Docker).
- [x] Validar que `alembic check`/`alembic current` está consistente com o metadata atual: `alembic check` → **No new upgrade operations detected** (foi necessário declarar no modelo `index=True` para `assets.size_bytes`/`assets.missing_at` — drift pré-existente da migração `202607290017`, não relacionado às remoções).
- [x] Conferir que nenhum teste que cria schema referencia tabelas/colunas removidas (suíte verde).

## Critérios de saída

- [x] Tabelas e colunas órfãs não existem mais no banco (verificado via `pg_tables`/`information_schema` — 0 resultados).
- [x] `alembic upgrade head` aplicado com sucesso (head `202608130026`) e `alembic check` consistente.
- [x] Nenhuma linha órfã com status de projeto removido (projetos intermediários movidos para `COMPLETED`; labels removidos nem podem mais ser referenciados).
- [x] A aplicação inicia e consulta o banco migrado (smoke: `create_app()` + SELECT em `projects` → OK).

## Execução (registro)

- Backup do banco de dev criado antes da migração: `storytelling_backup_20260813.sql` (417 KB, `pg_dump` via Docker) — **removido após a validação** para não ser versionado.
- `uv run pytest` → **500 passed, 5 failed (todas pré-existentes do baseline), 4 skipped**.
- `uv run mypy .` → 18 erros (mesmos do baseline); `uv run ruff check .` → All checks passed.
- Observação: `uv.lock` foi gerado incidentalmente pelo `uv run` (o projeto usa `requirements.lock`) e removido junto com o dump.

## Riscos e notas

- **Destrutivo**: a migração dropa dados. Backup obrigatório antes de executar em qualquer ambiente que não seja uma cópia de desenvolvimento.
- **Downgrade**: implementar `downgrade()` recriando as tabelas com o formato mínimo é trabalhoso; aceita-se um `downgrade` que apenas registre que as tabelas foram removidas (documentar a decisão no cabeçalho da migração).
- **Enum de projeto**: projetos existentes em estados intermediários são movidos para `COMPLETED` — confirmar com o solicitante antes de rodar em dados reais.
