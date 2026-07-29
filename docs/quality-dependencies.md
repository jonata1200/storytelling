# Qualidade, dependencias e operacao

Este documento concentra o fluxo local/CI, a arquitetura dos dominios e o
troubleshooting operacional usado antes de releases.

## Comandos de teste

Unitarios rapidos:

```powershell
python -m pytest -m unit
```

Integracao sem providers reais:

```powershell
python -m pytest -m "integration or ui or security or provider and not smoke"
```

Suite principal usada pela CI:

```powershell
ruff check .
mypy app tests
python -m pytest -m "not smoke"
```

Smokes reais de provider sao opt-in e podem gerar custo externo:

```powershell
$env:RUN_PROVIDER_SMOKE_TESTS = "1"
$env:OMNIROUTE_SMOKE = "1"
$env:OMNIROUTE_VIDEO_SMOKE = "1"
$env:OMNIROUTE_SPEECH_SMOKE = "1"
python -m pytest -m smoke
```

## Dependencias

- O lock atual foi mantido em `requirements.lock` e validado com `pip check`.
- A stack atual usa `fastapi==0.139.2`, `starlette` transitivo e `httpx==0.28.1`.
- O aviso conhecido de `starlette.testclient` fica filtrado no pytest ate a
  migracao dos testes sincronizados para `httpx.AsyncClient` com ASGI transport.
- Antes de atualizar para `httpx` major futuro, recrie o lock em ambiente limpo,
  rode `pip check`, `ruff`, `mypy` e a suite completa.

## Arquitetura

- `app/storytelling`: briefing, ideias, roteiro, cenas e planos.
- `app/visual_bible`: perfis visuais e referencias reutilizaveis.
- `app/storyboards`: frames, prompts aprovados, animatic e timeline preliminar.
- `app/video_generation`: jobs concorrentes, retry, idempotencia e clipes.
- `app/finalization`: vozes, legendas, montagem final e export.
- `app/storage`: metadados persistidos, reconciliacao local e limpeza segura.
- `app/costs`: politicas por operacao, budget e resumo por etapa/provider/modelo.
- `app/observability`: eventos operacionais, metricas de prompt/job e readiness.
- `app/ui`: cockpit NiceGUI e handlers de workspace.

## Fluxo de job

1. A UI ou API valida estado do projeto e dependencias.
2. O servico cria ou reutiliza `Artifact`/`ArtifactDependency`.
3. Jobs caros registram `GenerationJob`, budget estimado e evento operacional.
4. Providers geram arquivos em `LOCAL_STORAGE_PATH`.
5. Assets persistem `storage_uri`, `size_bytes`, `storage_checked_at` e versao inicial.
6. Custos gravam estimado, reportado pelo provider e valor final usado no budget.
7. Readiness e resumo do workspace exibem progresso, custo e falhas recentes.

## Troubleshooting

Postgres:

```powershell
docker compose ps postgres
alembic upgrade head
```

Redis:

```powershell
docker compose ps redis
python -m pytest tests/test_app_startup_readiness.py -q
```

Worker:

```powershell
celery -A app.jobs.celery_app inspect ping
```

OmniRoute:

```powershell
GET /api/v1/observability/readiness
```

Confira `OMNIROUTE_API_KEY`, modelos por canal e se os smokes foram ativados
explicitamente antes de chamar provider real.

## Checklist de release

- [ ] `pip check`
- [ ] `ruff check .`
- [ ] `mypy app tests`
- [ ] `python -m pytest -m "not smoke"`
- [ ] `alembic upgrade head` em banco limpo.
- [ ] Readiness sem segredos expostos.
- [ ] Smokes reais executados somente quando houver budget aprovado.
- [ ] Notas de migracao revisadas para novas colunas/tabelas.
