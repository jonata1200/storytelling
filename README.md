# Storytelling

Aplicacao para producao estruturada de historias emocionais em videos verticais,
com dominio versionado, aprovacao humana e pipeline recuperavel.

## Requisitos locais

- Python 3.12 ou superior
- Docker Desktop com WSL 2 no Windows
- Git
- FFmpeg sera necessario nas fases de renderizacao

## Configuracao

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.lock
pip install -e . --no-deps
Copy-Item .env.example .env
docker compose up -d
alembic upgrade head
uvicorn app.main:app --reload
```

O arquivo `requirements.lock` trava as versoes usadas em desenvolvimento e CI.
Quando dependencias mudarem em `pyproject.toml`, regenere o lock em um ambiente
limpo e rode `pip check`, `ruff check .`, `mypy app tests` e `pytest`.

Depois da primeira configuracao, voce pode usar o script unificado da pasta `scripts`:

```powershell
.\scripts\app.ps1 start
```

Para iniciar a API em segundo plano:

```powershell
.\scripts\app.ps1 start -Background
```

Para processar jobs longos em paralelo com a API, mantenha Redis ativo pelo
Docker Compose e inicie um worker Celery em outro terminal:

```powershell
celery -A app.workers.celery_app.celery_app worker --loglevel=info --pool=solo
```

Para finalizar a API e parar os containers:

```powershell
.\scripts\app.ps1 stop
```

Para reiniciar tudo em um unico comando:

```powershell
.\scripts\app.ps1 restart
```

Se o PowerShell bloquear scripts locais, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\app.ps1 start
```

Os atalhos `.\scripts\executar.ps1` e `.\scripts\finalizar.ps1` continuam
existindo por compatibilidade e chamam o script unificado.

## OpenRouter

A aplicacao usa modelos reais via OpenRouter no fluxo normal. Sem chave valida,
as etapas de IA retornam erro para a interface, em vez de gerar conteudo mock.
Configure no `.env`:

```env
OPENROUTER_API_KEY=sua_chave_aqui
OPENROUTER_DEFAULT_MODEL=deepseek/deepseek-v4-flash
OPENROUTER_IMAGE_MODEL=sourceful/riverflow-v2-fast
OPENROUTER_VIDEO_MODEL=bytedance/seedance-2.0-fast
ALLOW_USER_REGISTRATION=false
```

No workspace de cada projeto, use o bloco **Modelos de IA por etapa** para
definir modelos OpenRouter diferentes para ideias, roteiro e cenas/planos.
Modelos com sufixo `:free` e modelos `mock-*` sao bloqueados porque tendem a
falhar ou confundir o fluxo de producao.

Preferencias alteradas pela interface sao gravadas em `.runtime/preferences.json`.
O arquivo `.env` permanece somente para configuracao de inicializacao e nao e
modificado pela aplicacao em execucao.

Os providers reais atualmente implementados usam OpenRouter para texto, imagem e
video. A narracao final usa provider de fala OpenAI-compativel quando `SPEECH_API_KEY`
e `SPEECH_MODEL` estao configurados; provider mock de voz permanece bloqueado no fluxo.

## Experiencia de producao

A interface principal funciona como um cockpit de producao:

- Ideia inicial em linguagem natural.
- Core Setup com formato, resolucao, workflow e modelos.
- Passos guiados para narrativa, visual, storyboard, video, finalizacao e QA.
- Asset Canvas para personagens, cenarios, objetos e referencias.
- Storyboard Grid para revisar quadros antes de gerar clipes.
- Timeline Assembly para acompanhar a montagem.
- Criacao de proximo episodio herdando configuracoes e briefing.

Esse fluxo preserva o backend versionado ja existente, mas reorganiza o uso para
ficar mais proximo de uma plataforma full-pipeline de video com IA: primeiro a
ideia, depois configuracao de producao, ativos reutilizaveis, storyboard,
geracao de clipes, montagem e exportacao.

Se o comando `docker` nao aparecer no PowerShell logo apos instalar o Docker
Desktop, reinicie o VS Code/terminal ou use temporariamente:

```powershell
$env:Path = "C:\Program Files\Docker\Docker\resources\bin;$env:Path"
& "C:\Program Files\Docker\Docker\resources\bin\docker.exe" compose up -d
```

Interface:

```text
http://localhost:8000/
```

Health check:

```text
http://localhost:8000/api/v1/health/live
```

Autenticacao:

Em `APP_ENV=local` ou `APP_ENV=test`, a API operacional usa bypass local para
preservar a experiencia de desenvolvimento. Em ambientes fora de local/test, as
rotas operacionais em `/api/v1` exigem cookie de sessao ou token bearer gerado
pelo fluxo de login. O endpoint `/api/v1/health/live` permanece publico; o
readiness e as demais rotas exigem autenticacao quando a aplicacao nao esta em
ambiente local/test.

## Storage e custos

O storage local e auditavel por API. Os limites padrao podem ser ajustados no
`.env`:

```env
MAX_UPLOAD_BYTES=26214400
MAX_GENERATED_ASSET_BYTES=786432000
```

Endpoints operacionais:

```text
GET  /api/v1/storage/usage
GET  /api/v1/storage/projects/{project_id}/usage
GET  /api/v1/storage/orphans
POST /api/v1/storage/orphans/cleanup?dry_run=true
```

Custos e orcamentos usam uma politica padrao por operacao, com limites por
projeto e por etapa gravados em `project_production_settings.metadata_json`.
A geracao de video valida o limite antes de chamar o provider externo.

```text
GET   /api/v1/costs/policies
POST  /api/v1/costs/operation-estimate
GET   /api/v1/costs/projects/{project_id}/budget
PATCH /api/v1/costs/projects/{project_id}/budget
POST  /api/v1/costs/budget-check
GET   /api/v1/costs/projects/{project_id}/summary
```

## Finalizacao e observabilidade

A narracao final usa provider de fala real OpenAI-compativel. Configure no `.env`:

```env
SPEECH_PROVIDER=openai_compatible
SPEECH_BASE_URL=https://api.openai.com/v1
SPEECH_API_KEY=sua_chave_aqui
SPEECH_MODEL=seu_modelo_de_voz
SPEECH_VOICE=alloy
```

A exportacao final aceita perfil configuravel e tenta normalizar clipes via FFmpeg quando o
concat direto falha. Quando FFmpeg nao esta disponivel ou a renderizacao falha, o fluxo grava
um manifest estruturado com mensagem redigida.

Eventos operacionais por projeto ficam disponiveis em:

```text
GET /api/v1/observability/projects/{project_id}/events
GET /api/v1/observability/projects/{project_id}/summary
GET /api/v1/observability/readiness
```

O readiness separa API, banco, Redis, broker do worker, FFmpeg, OpenRouter e provider de voz.
Correlation ID e propagado por `X-Correlation-ID` nas chamadas externas relevantes.

## Testes

```powershell
python -m pytest
ruff check .
mypy app tests
```

Os testes automatizados nao devem chamar APIs pagas. Providers externos entram por
interfaces falsas nos testes; o fluxo da aplicacao nao deve escolher mocks.

## Estado atual

Fases 1 a 8 estao implementadas em base funcional:

- API FastAPI com UI NiceGUI inicial.
- PostgreSQL, pgvector e Redis via Docker Compose.
- Alembic async usando `asyncpg`.
- Projetos, versoes, artefatos, aprovacoes, dependencias, assets e custos.
- Maquina de estados inicial para o pipeline de projeto.
- Briefing, ideias, Story Bible, roteiro, cenas e planos com OpenRouter.
- Templates e execucoes de prompt auditaveis.
- Personagens, locais, objetos e referencias visuais reais via OpenRouter Images.
- Storyboards, narracao provisoria, animatic e timeline preliminar.
- Jobs de video via OpenRouter, clipes e revisao humana.
- Narracao final por provider de voz configuravel, legendas SRT, timeline final
  e export MP4/manifest.
- Continuity Ledger, quality gate, varredura inicial de seguranca e correlation
  ID por requisicao.
- Testes de health, maquina de estados, dependencias, custos e mock LLM.

## Fluxo narrativo inicial

Endpoints principais da Fase 3:

```text
POST /api/v1/storytelling/projects/{project_id}/briefing
POST /api/v1/storytelling/projects/{project_id}/ideas/generate
GET  /api/v1/storytelling/projects/{project_id}/ideas
POST /api/v1/storytelling/projects/{project_id}/story-bible/generate
POST /api/v1/storytelling/projects/{project_id}/script/generate
POST /api/v1/storytelling/projects/{project_id}/scenes/generate
```

As geracoes da Fase 3 usam OpenRouter no fluxo da aplicacao. Sem chave valida,
com modelo `:free` ou com modelo `mock-*`, a etapa retorna erro em vez de criar
conteudo falso.

## Fluxo visual inicial

Endpoints principais da Fase 4:

```text
POST /api/v1/visual-bible/projects/{project_id}/generate
GET  /api/v1/visual-bible/projects/{project_id}/characters
GET  /api/v1/visual-bible/projects/{project_id}/locations
GET  /api/v1/visual-bible/projects/{project_id}/props
POST /api/v1/visual-bible/projects/{project_id}/references/generate
GET  /api/v1/visual-bible/projects/{project_id}/consistency/{target_kind}/{target_id}
```

As referencias visuais usam OpenRouter Images. Fallback para imagem mock local
esta bloqueado; falhas do provedor devem aparecer como erro para o usuario.

## Fluxo de storyboard inicial

Endpoints principais da Fase 5:

```text
POST /api/v1/storyboards/projects/{project_id}/generate
GET  /api/v1/storyboards/projects/{project_id}/frames
POST /api/v1/storyboards/projects/{project_id}/animatic/generate
```

O animatic da Fase 5 e um manifesto JSON com quadros, duracoes, narracao
provisoria e timeline preliminar. Renderizacao em video fica para a fase de
FFmpeg.

## Fluxo de video inicial

Endpoints principais da Fase 6:

```text
POST /api/v1/video/projects/{project_id}/cost-estimate
POST /api/v1/video/projects/{project_id}/clips/generate
GET  /api/v1/video/projects/{project_id}/clips
GET  /api/v1/video/projects/{project_id}/jobs/{job_id}
POST /api/v1/video/projects/{project_id}/clips/{clip_id}/review
```

Os clipes usam OpenRouter Videos. Provider `mock` e modelo `mock-video` sao
recusados no fluxo da aplicacao.

## Fluxo de finalizacao inicial

Endpoints principais da Fase 7:

```text
POST /api/v1/finalization/projects/{project_id}/narration/generate
POST /api/v1/finalization/projects/{project_id}/subtitles/generate
POST /api/v1/finalization/projects/{project_id}/timeline/final
POST /api/v1/finalization/projects/{project_id}/exports
```

A geracao de narracao final usa provider de voz real configuravel. As legendas
sao geradas em SRT e a exportacao grava um manifesto JSON quando `ffmpeg` nao
esta disponivel no PATH ou quando a renderizacao falha.

## Fluxo de qualidade inicial

Endpoints principais da Fase 8:

```text
POST /api/v1/quality/projects/{project_id}/continuity/build
GET  /api/v1/quality/projects/{project_id}/continuity/issues
POST /api/v1/quality/projects/{project_id}/continuity/issues/{issue_id}/accept
POST /api/v1/quality/projects/{project_id}/checks/run
GET  /api/v1/quality/projects/{project_id}/observability
POST /api/v1/quality/security/scan
```

O controle de qualidade cria estados de continuidade por plano, alerta
divergencias estruturadas e resume jobs, custos, artefatos obsoletos e score de
qualidade do projeto.
