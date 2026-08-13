# Fase 3 — Remoção da dublagem

## Objetivo

Remover a etapa de dublagem da geração de vídeo e todo o código associado: módulo `app/dubbing/`, provider ElevenLabs de dubbing, etapa de job, endpoints, UI, configurações e integrações no agente de chat.

## Contexto / mapa de impacto

- Módulos: `app/dubbing/` (`models.py`, `schemas.py`, `service.py`) e `app/providers/dubbing/` (`elevenlabs.py`, `types.py`).
- Modelo `DubbingJob` (tabela `dubbing_jobs`) e migração `202607310018_dubbing_jobs.py`.
- `app/core/enums.py`: `ProjectStep.DUBBING`.
- `app/jobs/service.py` (`PROJECT_STEP_JOB_TYPES`) e `app/jobs/runner.py` (`_run_dubbing`).
- Endpoints de dubbing vivem dentro de `app/finalization/router.py` (serão removidos junto na Fase 4; nesta fase remover os imports/endpoints que quebram).
- Agente de chat: `app/generation/project_agent.py` (`_ensure_dubbing_pipeline`, ação `generate_dubbing`, blockers), `project_agent_routing.py` (termos "dublagem/dublar/idioma"), `project_agent_types.py` (ações/mensagens), `project_agent_context.py` (contagem `dubbing_jobs`).
- Observabilidade: `app/observability/service.py` (componente de readiness "dubbing").
- UI: `app/ui/workspace/storyboard_video_area.py` (área e ações de dubbing), `app/ui/shared/page_config.py`, `app/ui/workspace/rules.py`, `app/ui/workspace/panels.py`, `app/ui/routes/project_workspace_page.py`, `app/ui/page_runtime.py`, `app/ui/pages.py`, `app/ui/project/data.py`.
- Settings: `dubbing_provider`, `dubbing_source_lang`, `dubbing_target_lang`, `dubbing_poll_interval_seconds`, `dubbing_poll_timeout_seconds` (+ tela `app/ui/routes/settings_page.py` e `.env.example`).
- Visual Bible: `app/visual_bible/service.py` (blocker `dubbing_jobs`).
- Testes: `test_dubbing_service.py`, `test_elevenlabs_dubbing_provider.py`, `test_elevenlabs_smoke.py` (parte dubbing), `test_jobs.py`, `test_settings.py`, `test_observability_events.py`, `test_security_regressions.py`, `test_costs.py`, `test_project_creation_flow_cases.py` / `test_project_creation_workspace.py`.

## Checklist de ações

### Código de aplicação
- [x] Remover o diretório `app/dubbing/` por completo.
- [x] Remover o diretório `app/providers/dubbing/` por completo.
- [x] `app/core/enums.py`: remover `ProjectStep.DUBBING`.
- [x] `app/jobs/service.py`: remover `ProjectStep.DUBBING` de `PROJECT_STEP_JOB_TYPES`.
- [x] `app/jobs/runner.py`: remover `_run_dubbing` e o branch `elif step == ProjectStep.DUBBING`.
- [x] `app/finalization/router.py`: remover imports e endpoints de dubbing (`start_dubbing_job`, `start_project_dubbing`, `refresh_dubbing_job`, `list_dubbing_jobs`, `DubbingJobRead`, `DubbingStartRequest` e os 4 endpoints `/dubbing...`). O router será removido por completo na Fase 4.
- [x] `app/generation/project_agent.py`:
      - [x] Remover imports de `DubbingJob` e `start_project_dubbing`.
      - [x] Remover `_ensure_dubbing_pipeline` e o branch `if action == "generate_dubbing"`.
      - [x] Remover a entrada `("dublagem", DubbingJob)` de `SCRIPT_AGENT_EDIT_BLOCKER_MODELS`.
- [x] `app/generation/project_agent_routing.py`: remover termos de dubbing e os roteamentos para `generate_dubbing`.
- [x] `app/generation/project_agent_types.py`: remover `generate_dubbing` das ações e mensagens de progresso.
- [x] `app/generation/project_agent_context.py`: remover import e contagem de `DubbingJob` (campo `dubbing_jobs` do contexto).
- [x] `app/observability/service.py`: remover o bloco de readiness "dubbing" (`dubbing_configuration_status`).
- [x] `app/visual_bible/service.py`: remover `DubbingJob` de `VISUAL_RESET_BLOCKER_MODELS` e do mapa de labels.
- [x] `app/config/settings.py`: remover os 5 campos `dubbing_*`.
- [x] `.env.example`: remover o bloco `DUBBING_*`.
- [x] `app/ui/routes/settings_page.py`: remover os campos de configuração de dublagem.
- [x] `app/config/runtime_preferences.py`: conferir persistência de preferências `dubbing_*` e remover se houver.
- [x] `app/costs/service.py`: conferir se existe tabela de preço/operação `dubbing` e remover (ex.: `estimate_operation_cost` com operação "dubbing").
- [x] `app/projects/service.py`: remover `DELETE FROM dubbing_jobs` de `PROJECT_GRAPH_DELETE_STATEMENTS` e `"dubbing_jobs"` de `IDEA_GRAPH_TRUNCATE_TABLES`.
- [x] `app/providers/speech/service.py`: remover menção a dublagem na mensagem de readiness (`"...de vozes e dublagem"` → `"...de vozes"`).
- [x] `README.md`: remover `DUBBING_PROVIDER`, menção a "dublagem" em Recursos e resíduos de auth (`ALLOW_USER_REGISTRATION`/`SINGLE_USER_MODE`, linha `auth/` na estrutura, parágrafo sobre sessão/bearer).

### UI
- [x] `app/ui/workspace/storyboard_video_area.py`: remover `_enqueue_dubbing_from_ui`, `_refresh_dubbing_from_ui`, `render_dubbing_area`, `_dubbing_asset_url`, `_dubbing_cost_text` e o import de `refresh_dubbing_job`.
- [x] `app/ui/shared/page_config.py`: remover entradas de dubbing (tabs, `step_loading_copy`, mapa de ações `generate_dubbing`, contadores e validações).
- [x] `app/ui/workspace/rules.py`: remover `"dubbing"` de `WORKSPACE_SECTIONS` e das regras de acesso (e a variável `video_ready` que ficou sem uso).
- [x] `app/ui/workspace/panels.py`: remover o item "Dublagem" do resumo.
- [x] `app/ui/routes/project_workspace_page.py`: remover o branch `section == "dubbing"` e o parâmetro `render_dubbing_area`.
- [x] `app/ui/page_runtime.py` e `app/ui/pages.py`: remover `_render_dubbing_area` e re-export.
- [x] `app/ui/project/data.py`: remover import de `DubbingJob` e o campo `dubbing_job` do resumo (e o union no `project_counts_statement`).
- [x] `app/ui/project/assistant_panel.py`: remover textos/dicas de dublagem e a ação `generate_dubbing`.
- [x] `app/ui/layout/navigation.py`: remover `"dubbing"` de `WORKSPACE_NAV_ICONS`.

### Testes
- [x] Remover `tests/test_dubbing_service.py` e `tests/test_elevenlabs_dubbing_provider.py`.
- [x] `tests/test_elevenlabs_smoke.py`: remover o smoke de dubbing (manter o de speech, que permanece).
- [x] `tests/test_jobs.py`: remover as asserções de `dubbing` como step válido.
- [x] `tests/test_settings.py`: remover asserções de `dubbing_*`.
- [x] `tests/test_observability_events.py`: remover o teste de readiness de dubbing.
- [x] `tests/test_security_regressions.py`: remover referência a `dubbing_target_lang`.
- [x] `tests/test_costs.py`: ajustar teste de custo de dubbing.
- [x] `tests/_project_creation_flow_cases.py` / `test_project_creation_workspace.py`: remover casos das abas dubbing/finalização (os de finalização também caem na Fase 4).
- [x] `tests/test_api_keys.py` e `tests/test_continuous_video_interface.py`: remover referências a dubbing/`DUBBING_PROVIDER`.
- [x] `tests/test_ui_project_data.py`: atualizar `test_project_counts_statement_has_eighteen_unioned_selects` → `..._seventeen_unioned_selects` (17 selects / 16 unions após a remoção do union de `dubbing_jobs`).

### Verificação de resíduos
- [x] Buscar e zerar referências remanescentes (fora de `docs/` e migrações antigas):
      `dubbing`, `DubbingJob`, `generate_dubbing`, `dubbing_provider`, `dubbing_target_lang`,
      `ElevenLabsDubbingProvider`, `DubbingSubmit`, `DUBBING_` → **0 resultados**.
- [x] Rodar `uv run pytest`, `uv run mypy .` e `uv run ruff check .`:
      - `uv run pytest` → **524 passed, 5 failed (todas pré-existentes do baseline), 4 skipped**
      - `uv run mypy .` → **18 errors in 7 files** (mesmos do baseline, nenhum novo)
      - `uv run ruff check .` → **All checks passed**

## Critérios de saída

- [x] Zero referências a dublagem no código (exceto docs e migrações antigas).
- [x] Nenhuma aba/área "Dublagem" na UI; agente de chat não responde mais a pedidos de dublagem.
- [x] Suíte de testes, mypy e ruff sem **novas** falhas em relação ao baseline (5 falhas pré-existentes mantidas; a única falha nova causada pela fase — contagem de selects do `project_counts_statement` — foi corrigida no teste).

## Riscos e notas

- **Dependência da finalização**: o serviço de dubbing usava `Export` e `create_final_timeline`/`export_timeline` da finalização. Como a Fase 4 remove a finalização, não é necessário "substituir" essa dependência — apenas remover.
- **Speech ≠ Dubbing**: o speech de personagens (vozes dos diálogos via ElevenLabs) é um recurso separado e **permanece**.
