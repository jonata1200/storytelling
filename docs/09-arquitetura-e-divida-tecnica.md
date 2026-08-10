# Arquitetura e Dívida Técnica

---

## 9.1 Dois sistemas de autenticação

**Arquivos:** `app/auth/user_store.py` (JSON file) vs `app/auth/service.py` + `passwords.py`
(PostgreSQL). O primeiro é órfão (só testes). Consolidar em um só — ver
`04-codigo-morto-e-legado.md` item 4.1.

## 9.2 Ponte UI frágil via `getattr` em módulo

**Arquivos:** `app/ui/pages.py` e `app/ui/page_runtime.py`

`page_runtime._page_attr(name)` faz `getattr(sys.modules["app.ui.pages"], name)`. Todos os
símbolos da UI são re-exportados com `# noqa: F401` e acessados **por nome de string**.
Consequências:

- Renomear qualquer função quebra em **runtime** (AttributeError em uma página inteira),
  sem erro estático.
- O vulture aponta dezenas de "unused imports" (falsos positivos) que poluem a análise.
- A cadeia de dependência é difícil de seguir (pages → page_runtime → routes → workspace).

**Sugestão:** passar as funções como parâmetros já é o mecanismo usado em `register_*_pages`.
Eliminar a camada `_page_attr`/re-export e passar referências diretas na montagem
(`create_app`), ou mover a lógica de orquestração para um único módulo de composição.

## 9.3 Commit espalhado nos routers

**Arquivos:** `app/projects/router.py` (~linha 166, `post_artifact_approval` faz
`session.commit()`), `app/storage/router.py` (linhas 54, 68), `app/finalization/router.py`.

O padrão do projeto é "services fazem commit"; alguns endpoints commitam no router.
Manter consistência (tudo em services) evita commits parciais quando o fluxo evoluir.

## 9.4 Execução de jobs dentro do processo

**Arquivos:** `app/jobs/service.py`, `app/jobs/runner.py`

- `asyncio.create_task(run_job())` executa no mesmo processo do servidor.
- Sem worker externo, sem persistência da fila e sem recuperação no startup
  (ver `01-bugs-criticos.md` item 1.2).
- `GenerationJob` é **sobrecarregado**: serve tanto para "etapas de projeto"
  (`PROJECT_STEP_JOB_TYPES`) quanto para jobs de vídeo (`video_generation`).

**Sugestão:** a) adicionar recuperação de PENDING no startup; b) se houver plano de
escala, migrar para ARQ/RQ/Celery; c) separar o modelo de "project step" do de "media job".

## 9.5 Hack de atributo dinâmico em modelo SQLAlchemy

**Arquivo:** `app/jobs/service.py`

```python
cast(Any, job)._should_dispatch_after_enqueue = should_dispatch
```

Atributo definido dinamicamente após `session.refresh(job)` para comunicar à
`enqueue_project_step` se deve despachar. Funciona, mas é frágil (o atributo é perdido se
o objeto for re-lido). Melhor: retornar uma tupla/dataclass `(job, should_dispatch)`.

## 9.6 Duplicações de código

- `ffmpeg_exporter.render_timeline_video_with_audio` vs `finalization.service._render_timeline_video_with_audio`.
- `redact_secrets` em `observability/redaction.py` e `quality/security.py`.
- Laço duplicado em `video_generation/service.py`.

Ver `04-codigo-morto-e-legado.md` itens 4.2 e 4.8 e `01-bugs-criticos.md` item 1.4.

## 9.7 Arquivos monolíticos

| Arquivo | ~Linhas | Conteúdo |
|---------|--------|----------|
| `app/ui/routes/home_pages.py` | ~900 | home + criação de projeto + idea lab |
| `app/ui/pages.py` | ~700 | ponte + lógica de criação |
| `app/storytelling/service.py` | ~600 | ideias, roteiro, cenas |
| `app/video_generation/service.py` | ~900 | planejamento + execução + persistência |
| `app/finalization/service.py` | ~830 | timeline + fala + export |

Sugestão: extrair módulos por responsabilidade (ex.: `video_generation/executor.py`,
`finalization/render.py`) à medida que forem alterados.

## 9.8 Nomes mágicos de etapas

**Arquivos:** `app/jobs/service.py` (`PROJECT_STEP_JOB_TYPES`), `app/config/api_keys.py`
(`*_CREATION_STEPS`), `app/jobs/runner.py` (`if step == "script": ...`), `app/ui/*`.

Os nomes de etapa (`script`, `visual`, `storyboard`, `video`...) são strings espalhadas por
vários módulos. Adicionar um enum central (`app/core/enums.py` já existe) e tipar os
payloads de job evita erros de digitação e facilita renomear.

## 9.9 Configuração de providers redundante

- `settings.ai_provider` + `settings.text_provider` + `image_provider` + `video_provider`
  + `speech_provider` + `dubbing_provider` — com regras de "legacy default" em
  `effective_provider_for_channel` e `_optional_provider` (parâmetro morto).
- `provider_policy.provider_requires_api_key` sempre retorna `True`.

Simplificar: uma única tabela canal→provider→modelo por projeto (já existe
`project_model_settings` e `production_settings`) e derivar os defaults de forma única.

## 9.10 Tipagem dos modelos (`Base` sem `id`)

`app/database/base.py` expõe `UUIDPrimaryKeyMixin`/`TimestampMixin`, mas várias funções
genéricas tipam o modelo como `Base` e acessam `.id` — origem dos erros de mypy
(`"Base" has no attribute "id"`) em `storyboards/prompts.py` e
`visual_bible/reference_status.py`. Criar um `Protocol`/classe base tipada com `id`
resolve o problema de forma sistemática.

## 9.11 Config em arquivo JSON em vez de banco

`.runtime/preferences.json` guarda chaves e preferências com `lru_cache` +
`get_settings.cache_clear()`. Para aplicação multi-processo isso não sincroniza; para uso
local é suficiente. Documentar a limitação.

## 9.12 NiceGUI: upgrade 1.4 → 3.14

O código evoluiu junto com NiceGUI (agora 3.14), mas o piso no `pyproject.toml` ficou para
trás (ver `07-infraestrutura-e-ci.md` item 7.5). Recomenda-se fixar a versão e revisar
usos de API deprecada (ex.: `ui.refreshable`, `ui.navigate.reload`) periodicamente.

---

## Prioridade sugerida de refatoração

1. **Destravar o CI** (mypy/ruff — itens 9.10 + fixes pontuais).
2. **Unificar autenticação** (9.1) e remover código morto (item 4).
3. **Recuperação de jobs** no startup (9.4).
4. **Eliminar a ponte `_page_attr`** (9.2).
5. **Enum de etapas** (9.8) e simplificação de providers (9.9).
