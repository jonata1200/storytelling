# Fase 5 — Ajuste do pipeline de vídeo, estados e remoção da etapa de qualidade

## Objetivo

Aplicar a decisão D2: o pipeline de geração de vídeo passa a **terminar quando os clipes são gerados** — o projeto é marcado como concluído. Remove-se a revisão separada (`VIDEO_REVIEW`), os estados intermediários de áudio/montagem/qualidade e a etapa de qualidade (`ProjectStep.QUALITY` e módulo `app/quality/`).

## Contexto / mapa de impacto

- Estados de projeto órfãos: `VIDEO_REVIEW`, `AUDIO_GENERATION`, `ASSEMBLY`, `QUALITY_CONTROL`, `FINAL_APPROVAL`.
- `app/workflows/state_machine.py`: transições `VIDEO_GENERATION → VIDEO_REVIEW`, `VIDEO_REVIEW → AUDIO_GENERATION`, `AUDIO_GENERATION → ASSEMBLY`, `ASSEMBLY → QUALITY_CONTROL`, `QUALITY_CONTROL → FINAL_APPROVAL`, `FINAL_APPROVAL → COMPLETED`.
- Avanço de status após geração de clipes: `app/video_generation/service.py` (linha ~855) e `app/video_generation/continuous.py` (linha ~2250) avançam para `VIDEO_REVIEW`.
- `app/quality/`: `service.py`, `models.py`, `continuity.py`, `security.py` (conferir usos de `security_scan_text` fora do módulo antes de remover).
- Etapa de job `quality`: `app/core/enums.py` (`ProjectStep.QUALITY`), `app/jobs/service.py`, `app/jobs/runner.py` (`_run_quality`).
- Agente de chat: `app/generation/project_agent.py` (`_ensure_quality_pipeline`, ação `run_quality`), `project_agent_routing.py`, `project_agent_types.py`.
- UI: `app/ui/shared/page_config.py` (etapa QA, `step_loading_copy`, mapa de ações), `app/ui/project/production_steps.py`, `app/ui/workspace/panels.py`.
- `app/search_filters.py`: estágio "quality", `PROJECT_REVIEW_STATUSES`, `PROJECT_STAGE_BY_STATUS`.
- `app/projects/service.py` e telas de projeto: comportamento de "projeto concluído".
- Testes: `test_state_machine.py`, `test_quality_continuity.py`, `test_quality_security.py`, `test_search_filters.py`, `test_generation_progress.py`, `test_continuous_video_*`, `_project_agent_cases.py`.

## Checklist de ações

### Estados e máquina de estados
- [x] `app/core/enums.py`: remover `VIDEO_REVIEW`, `AUDIO_GENERATION`, `ASSEMBLY`, `QUALITY_CONTROL`, `FINAL_APPROVAL` de `ProjectStatus`.
- [x] `app/workflows/state_machine.py`: atualizar transições — `VIDEO_GENERATION` vai direto a `COMPLETED`:
      - [x] `VIDEO_GENERATION: {COMPLETED, FAILED}`
      - [x] Remover os nós `VIDEO_REVIEW`, `AUDIO_GENERATION`, `ASSEMBLY`, `QUALITY_CONTROL`, `FINAL_APPROVAL`.
      - [x] Conferir `QUALITY_CONTROL`/`ASSEMBLY`/`FINAL_APPROVAL` nas transições restantes (`COMPLETED`, `FAILED`) — nenhuma referência remanescente.
- [x] `app/video_generation/service.py`: ao concluir a geração dos clipes, avançar para `ProjectStatus.COMPLETED` (em vez de `VIDEO_REVIEW`).
- [x] `app/video_generation/continuous.py`: idem para segmentos contínuos (constantes `CONTINUOUS_VIDEO_REVIEW_*` são status de revisão por segmento e permanecem).

### Remoção da etapa de qualidade
- [x] `app/core/enums.py`: remover `ProjectStep.QUALITY`.
- [x] `app/jobs/service.py`: remover `ProjectStep.QUALITY` de `PROJECT_STEP_JOB_TYPES`.
- [x] `app/jobs/runner.py`: remover `_run_quality` e o branch `elif step == ProjectStep.QUALITY`.
- [x] Remover o módulo `app/quality/`:
      - [x] Conferir se `app/quality/security.py` (`security_scan_text`) é usado fora do módulo — **não é** (só dentro de `app/quality/`), módulo removido por completo.
      - [x] Remover `app/quality/models.py`, `service.py`, `continuity.py`, `router.py`, `schemas.py`, `security.py`.
- [x] `app/generation/project_agent.py`: remover import de `run_quality_check`, `_ensure_quality_pipeline` e o branch `if action == "run_quality"`.
- [x] `app/generation/project_agent_routing.py` e `project_agent_types.py`: remover a ação `run_quality` e termos associados; `_next_project_action` agora retorna `chat` quando o projeto está concluído.
- [x] `alembic/env.py`: remover import de `app.quality.models`.
- [x] `app/api/router.py`: remover `quality_router` e `quality_security_router`.
- [x] `app/projects/service.py`: remover `DELETE FROM quality_checks` e `"quality_checks"` do truncate.
- [x] `app/ui/project/data.py`: remover imports de `QualityCheck`/`ContinuityIssue`, union `qa_issues`, métrica "Alertas QA" do dashboard e campo `quality` do resumo.

### UI
- [x] `app/ui/shared/page_config.py`: remover a etapa QA de `PRODUCTION_STEPS`/tabs, `step_loading_copy`, mapa de ações `run_quality` e validações associadas.
- [x] `app/ui/project/production_steps.py`: remover a etapa de qualidade do fluxo de produção.
- [x] `app/ui/workspace/panels.py`: conferir — não havia painel/contagem de QA.
- [x] Conferir a tela de conclusão de projeto: status exibido via `project_status_bucket` ("done" → `COMPLETED`) e filtros por estágio — sem referências a revisão/qualidade.

### Filtros de busca
- [x] `app/search_filters.py`:
      - [x] Remover `"quality"` de `PROJECT_STAGE_FILTER_OPTIONS`.
      - [x] Remover `VIDEO_REVIEW` e `FINAL_APPROVAL` de `PROJECT_REVIEW_STATUSES`.
      - [x] Re-mapear `PROJECT_STAGE_BY_STATUS`: remover entradas de `AUDIO_GENERATION`, `ASSEMBLY`, `QUALITY_CONTROL`, `FINAL_APPROVAL`, `VIDEO_REVIEW`; `COMPLETED` passa a `"video"`; `FAILED`/`ARCHIVED` caem no fallback `"script"`.

### Testes
- [x] `test_state_machine.py`: conferir — testa apenas transições de `DRAFT`, sem referências aos estados removidos (sem alterações).
- [x] Remover `tests/test_quality_continuity.py` e `tests/test_quality_security.py` (e a entrada `test_quality_security.py` de `SECURITY_TEST_FILES` no `tests/conftest.py`).
- [x] `test_search_filters.py`: conferir — usa `stage_filter="video"`/`COMPLETED` sem asserções de estágios removidos (sem alterações).
- [x] `test_generation_progress.py` e `test_continuous_video_*`: conferir — nenhuma expectativa dos estados removidos (constantes `CONTINUOUS_VIDEO_REVIEW_*` são de segmento). `test_continuous_video_interface.py`: intent de avanço ajustado de `run_quality` → `chat`.
- [x] `_project_agent_cases.py`/`test_project_agent_routing.py`: remover o caso `run_quality` (teste virou `test_project_chat_routes_script_request`) e ajustar a classificação de "rode o controle de qualidade" → `generate_video`.
- [x] `test_ui_project_data.py`: atualizar contagens — dashboard 4→3 selects (2 unions) e counts 16→15 selects (14 unions).

### Verificação de resíduos
- [x] Buscar e zerar referências remanescentes (fora de `docs/` e migrações antigas):
      `VIDEO_REVIEW`, `AUDIO_GENERATION`, `ASSEMBLY`, `QUALITY_CONTROL`, `FINAL_APPROVAL`,
      `run_quality`, `ProjectStep.QUALITY`, `app.quality`, `QualityCheck`, `ContinuityIssue`,
      `security_scan_text` (avaliar), `build_continuity_ledger` → **0 resultados** (restam apenas `CONTINUOUS_VIDEO_REVIEW_*` de segmento e `quality_report` da normalização de story bible, que são outras features).
- [x] Rodar `uv run pytest`, `uv run mypy .` e `uv run ruff check .`:
      - `uv run pytest` → **500 passed, 5 failed (todas pré-existentes do baseline), 4 skipped**
      - `uv run mypy .` → **18 errors in 7 files** (mesmos do baseline, nenhum novo)
      - `uv run ruff check .` → **All checks passed**

## Critérios de saída

- [x] Ao gerar os clipes de vídeo, o projeto avança direto para `COMPLETED` (`app/video_generation/service.py` e `continuous.py`).
- [x] Zero referências aos estados/etapas removidos no código (exceto docs e migrações antigas).
- [x] Suíte de testes, mypy e ruff sem **novas** falhas em relação ao baseline (5 falhas pré-existentes mantidas).

## Riscos e notas

- **Enum no PostgreSQL**: os valores de `ProjectStatus` são um tipo ENUM no banco. A remoção dos valores do enum Python é feita nesta fase; a atualização do tipo no banco (mapear linhas existentes e remover valores) fica na Fase 6.
- **Revisão de clipes na UI**: a aba de vídeo pode ter controles de revisão/aprovação de clipes — ajustar para refletir que o projeto conclui ao final da geração.
