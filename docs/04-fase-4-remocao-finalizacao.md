# Fase 4 — Remoção da finalização

## Objetivo

Remover a etapa de finalização da geração de vídeo e todo o código associado: módulo `app/finalization/` (timeline final, export FFmpeg, legendas), etapa de job, endpoints, UI e integrações no agente de chat.

## Contexto / mapa de impacto

- Módulo `app/finalization/`: `ffmpeg_exporter.py`, `models.py` (`Export`, `SubtitleTrack`), `router.py`, `schemas.py`, `service.py`, `subtitles.py`.
- Tabelas `exports`, `subtitle_tracks`; migração `202607160007_phase7_finalization.py`.
- `app/api/router.py`: inclui `finalization_router`.
- `app/core/enums.py`: `ProjectStep.FINALIZATION` (e `ArtifactType.TIMELINE`/`EXPORT` — avaliar uso antes de remover).
- `app/jobs/service.py` (`PROJECT_STEP_JOB_TYPES`) e `app/jobs/runner.py` (`_run_finalization`).
- Agente de chat: `app/generation/project_agent.py` (`_ensure_finalization_pipeline`, ação `generate_finalization`, imports de `Export`/`SubtitleTrack`/`create_final_timeline`/`export_timeline`, blockers), `project_agent_routing.py` (termos de finalização), `project_agent_types.py` (ações/mensagens), `project_agent_context.py` (contagem `exports`).
- Visual Bible: `app/visual_bible/service.py` (blockers `exports`/`subtitle_tracks`).
- `alembic/env.py`: importa `app.finalization.models`.
- UI: `app/ui/workspace/storyboard_video_area.py` (área e ação de finalização), `app/ui/shared/page_config.py`, `app/ui/workspace/rules.py`, `app/ui/workspace/panels.py`, `app/ui/routes/project_workspace_page.py`, `app/ui/page_runtime.py`, `app/ui/pages.py`, `app/ui/project/data.py`, `app/ui/project/assistant_panel.py`, `app/ui/layout/navigation.py`.
- `app/search_filters.py`: estágio "finalization" e mapeamentos de status.
- Testes: `test_finalization_profile.py`, `test_subtitles.py`, `test_storyboard_timeline.py` (conferir), `_project_creation_flow_cases.py`/`test_project_creation_workspace.py` (abas), `_project_agent_cases.py`/`test_project_agent_routing.py`.

## Checklist de ações

### Código de aplicação
- [x] Remover o diretório `app/finalization/` por completo (`ffmpeg_exporter.py`, `models.py`, `router.py`, `schemas.py`, `service.py`, `subtitles.py`).
- [x] `app/api/router.py`: remover `finalization_router`.
- [x] `app/core/enums.py`: remover `ProjectStep.FINALIZATION` (e `GenerationJobType.RENDER`, que ficou sem uso).
- [x] Avaliar `ArtifactType.TIMELINE` e `ArtifactType.EXPORT`: `EXPORT` removido (só era usado pela finalização); `TIMELINE` **mantido** (usado pelo animatic em `app/storyboards/animatic.py`).
- [x] `app/jobs/service.py`: remover `ProjectStep.FINALIZATION` de `PROJECT_STEP_JOB_TYPES`.
- [x] `app/jobs/runner.py`: remover `_run_finalization` e o branch `elif step == ProjectStep.FINALIZATION` (e imports de `Timeline`/`Animatic` que ficaram órfãos).
- [x] `alembic/env.py`: remover o import de `app.finalization.models`.
- [x] `app/generation/project_agent.py`:
      - [x] Remover imports de `Export`, `SubtitleTrack`, `create_final_timeline`, `export_timeline`.
      - [x] Remover `_ensure_finalization_pipeline` e o branch `if action == "generate_finalization"`.
      - [x] Remover as entradas `("exportacoes", Export)` e `("legendas", SubtitleTrack)` de `SCRIPT_AGENT_EDIT_BLOCKER_MODELS`.
- [x] `app/generation/project_agent_routing.py`: remover termos de finalização e roteamentos para `generate_finalization` (incluindo o prompt da inferência por IA); `_next_project_action` agora retorna `run_quality` ao fim do vídeo.
- [x] `app/generation/project_agent_types.py`: remover `generate_finalization` das ações e mensagens de progresso.
- [x] `app/generation/project_agent_context.py`: remover import e contagem de `Export` (campo `exports` do contexto).
- [x] `app/visual_bible/service.py`: remover `Export` e `SubtitleTrack` de `VISUAL_RESET_BLOCKER_MODELS` e do mapa de labels.
- [x] `app/search_filters.py`:
      - [x] Remover `"finalization"` de `PROJECT_STAGE_FILTER_OPTIONS` e do mapa `PROJECT_STAGE_BY_STATUS` (statuses órfãos caem no fallback `"script"` até a Fase 5).
      - [x] Ajustes finais de status ficam na Fase 5 (quando `AUDIO_GENERATION`/`ASSEMBLY`/`FINAL_APPROVAL` deixarem de existir).
- [x] Manter `ffmpeg_path` (usado no readiness da observabilidade e pelo `app/video_generation/continuous.py`) — **mantido**.
- [x] `app/projects/service.py`: remover `DELETE FROM exports`/`DELETE FROM subtitle_tracks` de `PROJECT_GRAPH_DELETE_STATEMENTS` e `"exports"`/`"subtitle_tracks"` de `IDEA_GRAPH_TRUNCATE_TABLES`.
- [x] `README.md`: remover endpoint `/finalization/...`, linha `finalization/` na estrutura e menções a timeline/exportação em Recursos/intro.

### UI
- [x] `app/ui/workspace/storyboard_video_area.py`: remover `_enqueue_finalization_from_ui`, `render_finalization_area`, `_export_asset_url`, `_export_filename` e o import de `enqueue_project_step`.
- [x] `app/ui/shared/page_config.py`: remover entradas de finalização (etapa de `PRODUCTION_STEPS`, tab, `step_loading_copy`, mapa de ações `generate_finalization`, contadores, validações e `_progress_for_step`).
- [x] `app/ui/workspace/rules.py`: remover `"finalization"` de `WORKSPACE_SECTIONS`, `step_ready`, da seção de acesso (e `continuous_video_complete`/`_continuous_video_advance_message`, que ficaram sem uso).
- [x] `app/ui/workspace/panels.py`: remover item "Timeline" do cockpit e ajustar o texto (a faixa `_render_timeline_strip` do storyboard/vídeo **permanece**).
- [x] `app/ui/routes/project_workspace_page.py`: remover o branch `section == "finalization"` e o parâmetro `render_finalization_area`.
- [x] `app/ui/page_runtime.py` e `app/ui/pages.py`: remover `_render_finalization_area` e re-export.
- [x] `app/ui/project/data.py`: remover import de `Export`, o union `exports` do `project_counts_statement`, a métrica "Exports" do dashboard e os campos `latest_export`/`"export"` do resumo (timeline/timeline_items do storyboard permanecem).
- [x] `app/ui/project/assistant_panel.py`: remover textos/dicas de finalização e a ação `generate_finalization`.
- [x] `app/ui/layout/navigation.py`: remover `"finalization"` de `WORKSPACE_NAV_ICONS`.
- [x] `app/ui/project/production_steps.py`: remover a etapa `finalization` (mensagem, validação de clipes e imports órfãos `func`/`VideoClip`/`ContinuousVideoSegment`).

### Testes
- [x] Remover `tests/test_finalization_profile.py` e `tests/test_subtitles.py`.
- [x] Conferir `tests/test_storyboard_timeline.py`: testa apenas a timeline preliminar do storyboard (`app.storyboards.timeline`) — **sem ajustes necessários**.
- [x] `_project_creation_flow_cases.py`/`test_project_creation_workspace.py`: remover os casos das abas de finalização (`test_finalization_section_waits_for_video_clips`, `test_finalization_section_unlocks_after_video_clips`) e ajustar `test_workspace_tabs_start_with_script` para `["script", "assets", "video"]`.
- [x] `_project_agent_cases.py`/`test_project_agent_routing.py`: renomear `test_project_chat_routes_script_finalization_and_quality` → `test_project_chat_routes_script_and_quality` (sem o caso finalization) e ajustar a classificação de "exportar a timeline final" → `generate_video`.
- [x] `test_continuous_video_interface.py`: remover `test_continuous_finalization_requires_approved_segment` e `test_continuous_finalization_requires_minimum_three_approved_segments`; ajustar intent de avanço para `run_quality`.
- [x] `test_api_keys.py`: remover `test_finalization_step_uses_elevenlabs_key` e o import órfão `required_channels_for_creation_step`.
- [x] `test_ui_project_data.py`: atualizar contagens — dashboard 5→4 selects (3 unions) e counts 17→16 selects (15 unions).

### Verificação de resíduos
- [x] Buscar e zerar referências remanescentes (fora de `docs/` e migrações antigas):
      `finalization`, `Export`, `SubtitleTrack`, `create_final_timeline`, `export_timeline`,
      `generate_finalization`, `subtitle`, `ffmpeg_exporter`, `FinalTimelineRequest` → **0 resultados**.
- [x] Rodar `uv run pytest`, `uv run mypy .` e `uv run ruff check .`:
      - `uv run pytest` → **505 passed, 5 failed (todas pré-existentes do baseline), 4 skipped**
      - `uv run mypy .` → **18 errors in 7 files** (mesmos do baseline, nenhum novo)
      - `uv run ruff check .` → **All checks passed**

## Critérios de saída

- [x] Zero referências à finalização no código (exceto docs e migrações antigas).
- [x] Nenhuma aba/área "Finalização" na UI; agente de chat não responde mais a pedidos de finalização.
- [x] `Timeline`/`TimelineItem` do módulo `storyboards` **permanecem** (usados pelo animatic e UI de storyboard).
- [x] Suíte de testes, mypy e ruff sem **novas** falhas em relação ao baseline (5 falhas pré-existentes mantidas).

## Riscos e notas

- **Timeline compartilhada**: `Timeline`/`TimelineItem` vivem em `app/storyboards/models.py` e são criados também pelo animatic ("Timeline preliminar"). A remoção atinge apenas `create_final_timeline`/`export_timeline` da finalização, não o modelo nem a timeline preliminar.
- **Qualidade (Fase 5)**: a checagem de integridade de timeline em `app/quality/service.py` usava `Timeline` — será removida junto com o módulo de qualidade na Fase 5.
