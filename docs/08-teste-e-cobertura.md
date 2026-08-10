# Testes e Cobertura

> Status: **revisado em 10/08/2026** — os itens acionáveis foram corrigidos; vários já
> haviam sido resolvidos em rodadas anteriores (docs/03, 04, 05, 07) e foram confirmados.

---

## 8.1 Estado atual

- **61 arquivos de teste**, ~550 testes — todos passando (1 skip esperado), sem falhas.
- `ruff check app tests` ✅ · `mypy app tests` ✅ (280 arquivos) · `pytest tests -q` ✅.

---

## 8.2 Problemas

### 8.2.1 Testes exigem PostgreSQL e Redis reais

**Status: ✅ DOCUMENTADO**

- Adicionada nota no `README.md` (seção "Rodar testes"): a suíte exige PostgreSQL e
  Redis rodando via `docker compose up -d` (ou `.\scripts\story.ps1 run`); sem a
  infraestrutura, a suíte falha no setup.
- Perfil SQLite **não** implementado (avaliação): os modelos usam `JSONB` do PostgreSQL
  e enums nativos — um perfil SQLite exigiria abstrações de dialeto sem ganho real,
  já que o CI sobe os serviços corretamente.

### 8.2.2 `mypy app tests` falha (16 erros em testes)

**Status: ✅ JÁ RESOLVIDO** (rodada `03-erros-de-tipagem-e-lint.md`)

`mypy app tests` → `Success: no issues found in 280 source files`. Os exemplos citados
(`test_visual_bible_script_profiles.py:179,191`, `test_auth.py:385,386`) foram corrigidos
naquela rodada.

### 8.2.3 Testes exercitando módulo morto

**Status: ✅ JÁ RESOLVIDO** (rodada `04-codigo-morto-e-legado.md`)

`app/auth/user_store.py` foi removido e **nenhuma referência a `user_store`/`UserStore`
resta nos testes**. `test_security_regressions.py` hoje cobre segurança real (rotas sem
auth, preferências de runtime, storage, schemas, transições de status).

### 8.2.4 Teste "congela" comportamento morto

**Status: ✅ JÁ RESOLVIDO**

O teste `test_creative_narrative_tasks_do_not_allow_runtime_mock_fallback` **não existe
mais** — nenhuma referência a `runtime_mock`/`creative_narrative` nos testes, e
`allow_runtime_mock_fallback` não tem chamadores no `app/`. A limpeza já foi feita nas
rodadas anteriores; o teste morto não bloqueia mais futuras remoções.

---

## 8.3 Lacunas de cobertura — status

| Área | Risco | Status |
|------|-------|--------|
| Contrato do chat do Diretor IA (resposta não-JSON) | Alto | ✅ **Já coberto**: `test_openai_compatible_llm_provider.py` (2 testes: texto puro e JSON não-objeto para `director_agent_chat`) + `test_director_agent.py` (5 testes de `_extract_director_message`, incluindo raw content em texto puro) |
| Idea Lab: duração escolhida | Médio | ✅ **Já coberto**: `test_idea_lab_prompt_guides_quality_and_output_contract` (`duration_minutes=20`) + 2 testes de `generate_freeform_ideas` com `target_duration_minutes=6` e `=25` (clamp) |
| Recuperação de jobs PENDING após restart | Alto | ✅ **Coberto agora**: `pending_job_is_stale` (2 testes) + `list_stale_pending_jobs`/`list_stale_running_jobs` (2 testes novos com sessão falsa) + **redespacho de startup** (teste novo: `schedule_stale_job_recovery` com monkeypatch de `AsyncSessionLocal`, `list_stale_*` e `dispatch_project_job`) |
| Custo/orçamento com jobs retentados | Médio | ✅ **Coberto agora**: helper `_video_job_needs_generation` extraído (3 testes novos) — FAILED com tentativas restantes é regerado e cobrado; concluído/andamento/esgotado reusa sem cobrar |
| Truncamento de áudio de diálogo | Médio | ⏳ **Futuro** (não estava na lista de recomendações 8.4) |
| Fluxo morto em `_approve_video_prompts_from_ui` | Baixo | ⏳ **Futuro** (não estava na lista de recomendações 8.4) |
| Exportação degradada (sem ffmpeg/clipes) | Médio | ⏳ **Futuro** (não estava na lista de recomendações 8.4) |
| Purge "limpar banco" escondido na UI | Baixo | ⏳ **Futuro** (não estava na lista de recomendações 8.4) |
| Migrações vs modelos | Médio | ✅ **Coberto via CI**: `alembic check` adicionado em `docs/07` (item 7.6). Um teste estático sem banco seria frágil (renames/drops históricos nas migrações); a checagem real é o `alembic check` contra o Postgres do CI |

---

## 8.4 Recomendações — status

1. ✅ **Teste de `ask_director_agent` com texto puro** — já coberto (8.3 acima; recuperação
   `plain_text_message` + extração tolerante).
2. ✅ **Teste do Idea Lab com `target_duration_minutes=10`** — já coberto (variantes 6 e 25,
   além do prompt com 20).
3. ✅ **Teste de `pending_job_is_stale` + redespacho no startup** — coberto agora (4 testes
   novos em `tests/test_jobs.py`: staleness das listas + dispatch da recuperação).
4. ✅ **Teste da conta de `billable_seconds` com jobs FAILED a retentar** — coberto agora
   (helper `_video_job_needs_generation` + 3 testes novos em `tests/test_video_retry.py`).
5. ✅ **`alembic check` no CI** — feito em `docs/07` (item 7.6). Teste modelos vs migrações
   sem banco: dispensado por fragilidade (ver 8.3).
6. ✅ **Remover/re-escrever testes do `user_store.py`** — já resolvido (8.2.3).

## 8.5 Mudanças desta rodada

- `app/video_generation/service.py`: helper `_video_job_needs_generation` extraído da
  condição inline do laço de billing (comportamento idêntico, agora testável).
- `tests/test_video_retry.py`: 3 testes novos do helper.
- `tests/test_jobs.py`: 3 testes novos (2 de listas stale + 1 de redespacho no startup,
  com `_FakeStaleJobSession`/`_FakeStaleJobResult` e monkeypatch dos módulos reais).
- `README.md`: nota de que os testes exigem PostgreSQL/Redis (`docker compose up -d`).
- Validação: ruff ✅ · mypy (280 arquivos) ✅ · pytest completo ✅ (1 skip).
