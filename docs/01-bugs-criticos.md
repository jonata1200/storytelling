# Bugs Críticos

Problemas com impacto direto no uso da aplicação (falhas perceptíveis, travamentos,
inconsistências de dados ou de qualidade) e que devem ser corrigidos primeiro.

> **Status (10/08/2026):** todos os itens abaixo foram corrigidos. Cada seção indica o que
> foi feito. Ver também `02-bugs-funcionais.md` (correção da duração no Idea Lab fica para a
> próxima rodada de correções).

---

## 1.1 Chat do Diretor IA: contrato de resposta frágil (erros de JSON frequentes) — ✅ corrigido

**Arquivos:** `app/generation/director_agent.py`, `app/providers/llm/openai_compatible.py`,
`app/providers/llm/ollama_cloud.py`

O chat do assistente chama `run_structured_generation` com o template
`director_agent_chat = "{prompt}"` e lê `result.content.get("message")`
(`director_agent.py` ~linha 72). Porém:

- O prompt enviado **não instrui o modelo a responder em JSON** — pede texto natural
  ("Responda em português do Brasil, de forma prática, criativa e curta").
- Os providers, por outro lado, **forçam JSON**: `openai_compatible.py` envia
  `response_format={"type": "json_object"}` e o `ollama_cloud.py` instrui
  "Responda somente com JSON valido". O parser `_parse_json_content` lança
  `OpenAICompatibleResponseFormatError` se o texto não for JSON.

**Efeito:** respostas em texto puro do modelo (muito comuns em chat livre) viram erro
"provider retornou conteúdo que não é json válido" e o usuário não recebe a resposta.

**Correção aplicada:**
1. `director_agent.py` — o prompt agora instrui o formato exato
   `{"message": "..."}` (reduz respostas fora de JSON).
2. `openai_compatible.py::_parse_json_content` — para a tarefa `director_agent_chat`,
   respostas em texto puro (ou JSON não-objeto) são embrulhadas em `{"message": ...}`
   com `recovery_strategy="plain_text_message"` em vez de falhar.
3. `director_agent.py::_extract_director_message` — extração defensiva: tenta
   `message` → `response`/`answer`/`reply`/`text` → texto puro do `raw_content` (apenas se
   não começar com `{`) → mensagem padrão. Evita `AttributeError` e evita exibir JSON cru.

---

## 1.2 Jobs em memória: sem recuperação após reinício (job PENDING travado) — ✅ corrigido

**Arquivos:** `app/jobs/service.py`, `app/jobs/runner.py`, `app/factory.py`

A execução das etapas longas é feita **no próprio processo** via
`asyncio.create_task(run_job(), ...)` (`jobs/service.py` ~linha 272), sem worker externo e
sem persistência da fila. Se a aplicação reiniciar durante uma etapa, o job fica `PENDING`
e nunca era redespachado automaticamente.

**Correção aplicada:**
- `jobs/service.py` — novas funções `list_stale_pending_jobs(session)` e
  `list_stale_running_jobs(session)` + `schedule_stale_job_recovery()`: recupera jobs
  `PENDING` **e** `RUNNING` abandonados (processo morto no meio da etapa) com `updated_at`
  mais antigo que `PENDING_JOB_REDISPATCH_AFTER`, redespachando-os via `dispatch_project_job`.
- `schedule_stale_job_recovery` é ignorada em `APP_ENV=test` para não interferir na suíte.
- `factory.py` — `schedule_stale_job_recovery` registrado como hook de **startup** do
  FastAPI (roda em background, sem bloquear o boot).

---

## 1.3 "Limpar banco da aplicação" escondido na UI — ✅ corrigido

**Arquivo:** `app/ui/routes/settings_page.py`

Na aba Dados, o terceiro card ("Projetos e ideias" → "Limpar definitivamente" →
`purge_dialog`) estava dentro de `ui.element("div").classes("hidden")` — o diálogo existia,
mas **não havia botão visível** para abri-lo.

**Correção aplicada:** removida a classe `hidden`; o card agora é exibido com o mesmo
estilo dos demais cards destrutivos da aba Dados.

---

## 1.4 Laço duplicado na geração de vídeo — ✅ corrigido (duplicação removida)

**Arquivo:** `app/video_generation/service.py` (`_generate_video_clips_concurrent`)

**Nota de correção do diagnóstico:** a afirmação anterior de que "jobs `FAILED` retentados
não entram na conta de `billable_seconds`" estava **incorreta** — a condição do primeiro
laço já contabilizava esses jobs. O problema real era a **duplicação integral do laço**
(duas varreduras com as mesmas queries de idempotência), que tende a divergir.

**Correção aplicada:** os dois laços foram unificados:
1. **Planejamento** (uma única varredura): monta `_PlannedVideoJob` por frame/variante,
   coleta jobs/clipes já existentes e calcula `billable_seconds` exatamente para o
   conjunto que será executado (novos + retentativas).
2. **Checagem de orçamento** sobre esse conjunto.
3. **Criação/reativação** dos jobs a partir do plano.

Comportamento preservado (mesmas queries, mesmos eventos, mesma ordem de commits) com o
código duplicado eliminado.

---

## 1.5 Áudio de diálogo truncado silenciosamente — ✅ corrigido

**Arquivo:** `app/finalization/service.py` (`_add_dialogue_audio_items`)

Se a fala sintetizada for mais longa que o frame, o áudio era **cortado no fim do frame**
sem qualquer registro.

**Correção aplicada:**
- Adicionado `logger` ao módulo.
- Quando `truncated_ms > 0`, um **warning é logado** (`dialogue_truncated frame=...`).
- O valor `truncated_ms` é incluído nas `properties` do `TimelineItem` e nos `details` do
  evento de observabilidade, permitindo auditar os cortes na UI/relatórios.

---

## 1.6 Inconsistência de montagem de storage em `APP_ENV=development` — ✅ corrigido

**Arquivo:** `app/factory.py`

```python
LOCAL_STORAGE_MOUNT_ENVS = {"local", "development", "test"}   # development adicionado
```

Em `APP_ENV=development`, o `/storage` agora é montado, eliminando os 404 dos assets
locais (imagens, vídeos, exportações) nesse ambiente.

---

## 1.7 Jobs duplicados por requisições concorrentes na mesma etapa — ✅ corrigido

**Arquivo:** `app/jobs/service.py` (`create_or_resume_project_job`)

**Nota de correção do diagnóstico:** a `UniqueConstraint(idempotency_key)` **já existia**
no modelo (`app/video_generation/models.py:37`, `unique=True`) e na migração
`202607160006_phase6_video_generation.py` — o banco já impede jobs duplicados. O risco
restante era um `IntegrityError` não tratado (500) caso duas requisições concorrentes
inserissem a mesma chave.

**Correção aplicada:** o `flush` do novo job agora trata `IntegrityError`: faz rollback,
recarrega o job existente pela `idempotency_key` e o reutiliza, em vez de estourar 500.

---

## 1.8 `_approve_video_prompts_from_ui` — fluxo antigo morto — ✅ corrigido

**Arquivo:** `app/ui/visual/actions.py`

Após enfileirar o job de vídeo, a função fazia `return` e um bloco inteiro de código morto
(referências a `result`, `jobs`, `clips` do fluxo antigo) permanecia inalcançável.

**Correção aplicada:** bloco morto removido; a função agora enfileira o job, notifica e
recarrega a página.
