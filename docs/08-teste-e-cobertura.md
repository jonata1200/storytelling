# Testes e Cobertura

---

## 8.1 Estado atual

- **60 arquivos de teste**, ~540 testes.
- Execução local (com PostgreSQL e Redis rodando via Docker): **todos passam**,
  com ~5 testes pulados (`s`), sem falhas.
- Comandos: `.venv/Scripts/python.exe -m pytest tests -q`.

## 8.2 Problemas

### 8.2.1 Testes exigem PostgreSQL e Redis reais

`tests/conftest.py` aponta para o banco real via `DATABASE_URL`/`REDIS_URL`. Sem Docker
rodando, a suíte inteira falha no setup. Não há banco em memória (SQLite/aiosqlite) nem
containers gerenciados pelo pytest. O CI sobe os serviços — OK para CI, mas ruim para
desenvolvimento local rápido.

**Sugestão:** documentar que `scripts/story.ps1 tools test` exige `docker compose up -d`
antes; avaliar um perfil de testes com SQLite (com cuidado para tipos `JSONB`/pgvector).

### 8.2.2 `mypy app tests` falha (16 erros em testes)

O CI roda mypy sobre os testes e ele falha (ver `03-erros-de-tipagem-e-lint.md` item 3.3).
Exemplos: `test_visual_bible_script_profiles.py:179,191`,
`test_auth.py:385,386`.

### 8.2.3 Testes exercitando módulo morto

`tests/test_security_regressions.py` testa `app/auth/user_store.py` — módulo que a
aplicação não usa (ver `04-codigo-morto-e-legado.md` item 4.1). Gera falsa sensação de
cobertura de auth.

### 8.2.4 Teste "congela" comportamento morto

`tests/test_prompt_compiler.py:114` (`test_creative_narrative_tasks_do_not_allow_runtime_mock_fallback`)
asserta que `allow_runtime_mock_fallback` retorna `False` — uma função que a aplicação não
chama. O teste impede futuras limpezas.

## 8.3 Lacunas de cobertura (áreas sem teste ou com teste raso)

| Área | Risco | Observação |
|------|-------|------------|
| Contrato do chat do Diretor IA (resposta não-JSON) | Alto | `director_agent.py` + `openai_compatible._parse_json_content` — sem teste para resposta em texto puro |
| Idea Lab: duração escolhida | Médio | `idea_lab.py` ignora `target_duration_minutes` — nenhum teste cobre o parâmetro |
| Recuperação de jobs PENDING após restart | Alto | `jobs/service.py` — sem teste de redespacho |
| Custo/orçamento com jobs retentados | Médio | `video_generation/service.py` — sem teste do caso FAILED→retry no orçamento |
| Truncamento de áudio de diálogo | Médio | `finalization/service.py` — sem teste de fala maior que o frame |
| Fluxo morto em `_approve_video_prompts_from_ui` | Baixo | código inalcançável não é exercitado |
| Exportação degradada (sem ffmpeg/clipes) | Médio | `finalization/service.py` — branch `MANIFEST_ONLY` sem teste |
| Purge "limpar banco" escondido na UI | Baixo | settings_page — sem teste de visibilidade |
| Migrações vs modelos | Médio | nenhum `alembic check` no CI |

## 8.4 Recomendações

1. Adicionar teste para `ask_director_agent` quando o provider devolve texto puro.
2. Adicionar teste do Idea Lab que passa `target_duration_minutes=10` e verifica o prompt.
3. Testar `pending_job_is_stale` + redespacho no startup (função nova sugerida).
4. Testar a conta de `billable_seconds` quando existem jobs FAILED a retentar.
5. Rodar `alembic check` no CI e um teste que compare modelos vs. migrações.
6. Remover testes do `user_store.py` morto ou reescrevê-los para o sistema real de auth.
