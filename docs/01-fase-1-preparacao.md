# Fase 1 — Preparação e baseline

## Objetivo

Garantir um ponto de partida estável e verificável antes de qualquer remoção: suíte verde, ferramentas funcionando, branch isolado e decisões confirmadas.

## Contexto

O repositório usa `uv` (há `requirements.lock`), pytest com `asyncio_mode = auto`, mypy e ruff configurados no `pyproject.toml`. Os comandos abaixo usam `uv run`; ajuste se o ambiente local usa outro gerenciador.

## Checklist de ações

- [x] Criar branch de trabalho a partir de `main`: **`feat/remove-auth-dubbing-finalization`** (criada).
- [x] Rodar a suíte de testes completa e registrar o resultado como baseline:
      `uv run pytest` → **551 passed, 5 failed, 5 skipped**
- [x] Rodar typecheck e lint como baseline:
      `uv run mypy .` → **18 errors in 7 files**
      `uv run ruff check .` → **All checks passed**
- [x] Confirmar que os comandos acima rodam e registrar o estado **antes** de iniciar as remoções
      (nota: as falhas abaixo são pré-existentes na `main`, verificadas antes de qualquer mudança de código).
- [x] Reconfirmar com o solicitante as decisões D1 e D2 do [`00-plano-geral.md`](00-plano-geral.md)
      (confirmadas ao criar o plano, via questionário).
- [ ] (Recomendado) Criar um backup do banco de desenvolvimento antes da Fase 6
      (as migrações irão dropar tabelas com dados) — **pendente, executar antes da Fase 6**.
- [x] Anotar aqui o resultado do baseline para comparação na Fase 7:

  | Verificação | Resultado esperado | Resultado obtido |
  |-------------|--------------------|------------------|
  | `uv run pytest` | 0 falhas | **551 passed, 5 failed, 5 skipped** (falhas pré-existentes na `main`) |
  | `uv run mypy .` | 0 erros | **18 errors in 7 files** (pré-existentes) |
  | `uv run ruff check .` | 0 erros | **All checks passed** |

## Falhas pré-existentes registradas (não causadas pelo plano)

Suíte: 5 falhas, todas reproduzidas na `main` antes de qualquer mudança:

1. `tests/test_app_startup_readiness.py::test_readiness_dashboard_degrades_without_redis_and_providers` — `AttributeError: module 'app.observability.service' has no attribute 'shutil'`.
2. `tests/test_project_agent_routing.py::test_project_chat_routes_assets_storyboard_and_video` — `AttributeError: 'object' object has no attribute 'execute'`.
3. `tests/test_project_agent_routing.py::test_project_chat_routes_storyboard_scene_requests` — idem.
4. `tests/test_project_agent_routing.py::test_project_chat_routes_storyboard_prompt_approval` — idem.
5. `tests/test_project_creation_workspace.py::test_retry_initial_script_opens_loading_dialog_and_watches_status` — `AttributeError: module 'app.ui.pages' has no attribute '_generate_initial_script_in_background'`.

Mypy: 18 erros em 7 arquivos — `app/video_generation/continuous.py` (union-attr) e 6 arquivos de teste (`test_continuous_video_segments.py`, `test_storyboard_timeline.py`, `test_generation_progress.py`, `_project_creation_flow_cases.py`, `test_app_startup_readiness.py`, entre outros).

> A comparação final (Fase 7) deve usar este baseline: o objetivo é **não aumentar** o número de falhas/erros, e idealmente os resíduos de auth/dubbing/finalization/quality desaparecerem junto com os arquivos de teste que os referenciam.

## Critérios de saída

- [x] Suíte, mypy e ruff executados e registrados na tabela acima (estado pré-existente documentado).
- [x] Branch de trabalho criada: `feat/remove-auth-dubbing-finalization`.
- [x] Decisões D1 e D2 confirmadas e registradas (ver `00-plano-geral.md`).

## Riscos e notas

- Rodar os testes pode exigir serviços externos (PostgreSQL/Redis via docker-compose). Se parte da suíte exigir infraestrutura, registre quais testes rodam sem ela para não confundir falha de ambiente com regressão nas fases seguintes.
