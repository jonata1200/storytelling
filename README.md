# Storytelling

Aplicação para produção estruturada de histórias emocionais em vídeos verticais,
com domínio versionado, aprovação humana e pipeline recuperável.

## Requisitos locais

- Python 3.12 ou superior
- Docker Desktop com WSL 2 no Windows
- Git
- FFmpeg será necessário nas fases de renderização

## Configuração

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

O arquivo `requirements.lock` trava as versões usadas em desenvolvimento e CI.
Quando dependências mudarem em `pyproject.toml`, regenere o lock em um ambiente
limpo e rode `pip check`, `ruff check .`, `mypy app tests` e `pytest`.

Depois da primeira configuração, você pode usar o script unificado da pasta `scripts`:

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

Para reiniciar tudo em um único comando:

```powershell
.\scripts\app.ps1 restart
```

Se o PowerShell bloquear scripts locais, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\app.ps1 start
```

Os atalhos `.\scripts\executar.ps1` e `.\scripts\finalizar.ps1` continuam
existindo por compatibilidade e chamam o script unificado.

## Provedores de IA

OmniRoute é o provider único para texto, imagem e vídeo. Sem chave válida, as
etapas de IA retornam erro para a interface, em vez de gerar conteúdo mock.
Configure no `.env`:

```env
OMNIROUTE_API_KEY=sua_chave_aqui
AI_PROVIDER=omniroute
TEXT_PROVIDER=
IMAGE_PROVIDER=
VIDEO_PROVIDER=
OMNIROUTE_BASE_URL=https://omnirouters.com/v1
OMNIROUTE_DEFAULT_MODEL=ds-web/deepseek-v4-flash
OMNIROUTE_IMAGE_MODEL=chatgpt-web/gpt-5.5
OMNIROUTE_VIDEO_MODEL=veo-free/veo
OMNIROUTE_SPEECH_MODEL=
SPEECH_PROVIDER=openai_compatible
SPEECH_MODEL=
ALLOW_USER_REGISTRATION=true
SINGLE_USER_MODE=true
```

No workspace de cada projeto, use o bloco **Modelos de IA por etapa** para
definir provider e modelos diferentes para ideias, roteiro, cenas/planos,
biblioteca visual e prompts de storyboard.
Modelos com sufixo `:free` e modelos `mock-*` são bloqueados porque tendem a
falhar ou confundir o fluxo de produção.

OmniRoute pode ser configurado globalmente por `AI_PROVIDER=omniroute` ou por
mídia (`TEXT_PROVIDER`, `IMAGE_PROVIDER`, `VIDEO_PROVIDER`).
Para vozes dos personagens, use
`SPEECH_PROVIDER=omniroute` com `OMNIROUTE_API_KEY` e `OMNIROUTE_SPEECH_MODEL`
ou mantenha `SPEECH_PROVIDER=openai_compatible`.

Preferências não sensíveis alteradas pela interface são gravadas em
`.runtime/preferences.json`. Segredos como `OMNIROUTE_API_KEY` e `SPEECH_API_KEY`
devem ficar somente no `.env` ou nas variáveis do ambiente; a aplicação não
persiste esses valores no arquivo runtime.

Os providers reais atualmente implementados usam OmniRoute para texto, imagem e
vídeo. Os clipes são gerados sem narração
nativa; o roteiro e a decupagem priorizam
interação e diálogo entre personagens. Na finalização, falas presentes em
`dialogue_text` podem ser sintetizadas como vozes de personagens quando
o provider de speech escolhido está configurado.

## Experiência de produção

A interface principal funciona como um cockpit de produção:

- Ideia inicial em linguagem natural.
- Core Setup com formato, resolucao, workflow e modelos.
- Passos guiados para narrativa, cenas/planos, visual, storyboard, vídeo, finalização e QA.
- Asset Canvas para personagens, cenários, objetos e referências.
- Storyboard Grid para revisar quadros antes de gerar clipes.
- Timeline Assembly para acompanhar a montagem.
- Criação de próximo episódio herdando configurações e briefing.

Esse fluxo preserva o backend versionado já existente, mas reorganiza o uso para
ficar mais próximo de uma plataforma full-pipeline de vídeo com IA: primeiro a
ideia, depois configuração de produção, ativos reutilizáveis, storyboard,
geração de clipes, montagem e exportação.

Se o comando `docker` não aparecer no PowerShell logo após instalar o Docker
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

Autenticação:

Em `APP_ENV=local` ou `APP_ENV=test`, a API operacional usa bypass local para
preservar a experiência de desenvolvimento. Em ambientes fora de local/test, as
rotas operacionais em `/api/v1` exigem cookie de sessão ou token bearer gerado
pelo fluxo de login. O endpoint `/api/v1/health/live` permanece público; o
readiness e as demais rotas exigem autenticação quando a aplicação não está em
ambiente local/test.

O cadastro usa e-mail como login e exige senha forte: pelo menos 6 caracteres,
com letra maiúscula, letra minúscula, número e símbolo. Com
`SINGLE_USER_MODE=true`, apenas o primeiro cadastro é permitido; depois disso a
tela de cadastro é bloqueada e o link "Criar uma conta" desaparece do login.
O usuário autenticado pode sair pelo botão **Sair** na navegação da aplicação.
Sessões novas são persistidas no banco com expiração e podem ser revogadas no
logout sem trocar `APP_SECRET_KEY`. Formulários HTML mutantes usam token CSRF
assinado; em produção, mantenha `APP_SECRET_KEY` forte, `APP_DEBUG=false` e
execute `alembic upgrade head` antes de expor a aplicação.

Checklist mínimo para produção:

```env
APP_ENV=production
APP_DEBUG=false
APP_SECRET_KEY=gere-um-segredo-longo-e-unico
ALLOW_USER_REGISTRATION=false
OMNIROUTE_API_KEY=sua_chave_no_ambiente
```

## Storage e custos

O storage local é auditável por API. Os limites padrão podem ser ajustados no
`.env`:

```env
MAX_UPLOAD_BYTES=26214400
MAX_GENERATED_ASSET_BYTES=786432000
```

Endpoints operacionais:

```text
GET  /api/v1/storage/usage
GET  /api/v1/storage/projects/{project_id}/usage
POST /api/v1/storage/reconcile
POST /api/v1/storage/projects/{project_id}/reconcile
GET  /api/v1/storage/orphans
POST /api/v1/storage/orphans/cleanup?dry_run=true
POST /api/v1/storage/orphans/cleanup?dry_run=false&confirm=true
```

`/usage` usa `size_bytes` persistido para abrir rapido. A varredura completa de
arquivos locais fica nos endpoints administrativos de `reconcile`, `orphans` e
`cleanup`, que aceitam filtros por `project_id`, `kind` e `older_than_days`.

Custos e orçamentos usam uma política padrão por operação, com limites por
projeto e por etapa gravados em `project_production_settings.metadata_json`.
A geração de vídeo valida o limite antes de chamar o provider externo.

```text
GET   /api/v1/costs/policies
POST  /api/v1/costs/operation-estimate
GET   /api/v1/costs/projects/{project_id}/budget
PATCH /api/v1/costs/projects/{project_id}/budget
POST  /api/v1/costs/budget-check
GET   /api/v1/costs/projects/{project_id}/summary
```

## Finalização e observabilidade

A exportação final aceita perfil configurável e tenta normalizar clipes via FFmpeg quando o
concat direto falha. Quando FFmpeg não está disponível ou a renderização falha, o fluxo grava
um manifest estruturado com mensagem redigida.

Eventos operacionais por projeto ficam disponíveis em:

```text
GET /api/v1/observability/projects/{project_id}/events
GET /api/v1/observability/projects/{project_id}/summary
GET /api/v1/observability/readiness
```

O readiness separa API, banco, Redis, broker do worker, FFmpeg, providers de
texto, imagem, vídeo e vozes de personagens.
Correlation ID é propagado por `X-Correlation-ID` nas chamadas externas relevantes.

## Testes

```powershell
ruff check .
mypy app tests
python -m pytest -m "not smoke"
```

Os testes automatizados não devem chamar APIs pagas. Providers externos entram por
interfaces falsas nos testes; smokes reais exigem `RUN_PROVIDER_SMOKE_TESTS=1`
e variáveis específicas como `OMNIROUTE_SMOKE=1`.

Detalhes de comandos por marcador, troubleshooting e checklist de release ficam em
[`docs/quality-dependencies.md`](docs/quality-dependencies.md).

## Estado atual

Fases 1 a 8 estão implementadas em base funcional:

- API FastAPI com UI NiceGUI inicial.
- PostgreSQL, pgvector e Redis via Docker Compose.
- Alembic async usando `asyncpg`.
- Projetos, versões, artefatos, aprovações, dependências, assets e custos.
- Máquina de estados inicial para o pipeline de projeto.
- Briefing, ideias, Story Bible, roteiro, cenas e planos com OmniRoute.
- Templates e execuções de prompt auditáveis.
- Personagens, locais, objetos e referências visuais reais via OmniRoute Images.
- Storyboards, animatic visual e timeline preliminar.
- Jobs de vídeo via OmniRoute, clipes e revisão humana.
- Timeline final e export MP4/manifest sem narração, com mix de vozes por personagem.
- Continuity Ledger, quality gate, varredura inicial de segurança e correlation
  ID por requisição.
- Testes de health, maquina de estados, dependências, custos e mock LLM.

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

As gerações da Fase 3 usam o provider de texto configurado no fluxo da aplicação. Sem chave válida,
com modelo `:free` ou com modelo `mock-*`, a etapa retorna erro em vez de criar
conteúdo falso.

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

As referências visuais usam o provider de imagem configurado. Fallback para imagem mock local
está bloqueado; falhas do provedor devem aparecer como erro para o usuário.

## Fluxo de storyboard inicial

Endpoints principais da Fase 5:

```text
POST /api/v1/storyboards/projects/{project_id}/generate
GET  /api/v1/storyboards/projects/{project_id}/frames
POST /api/v1/storyboards/projects/{project_id}/animatic/generate
```

O animatic da Fase 5 é um manifesto JSON com quadros, durações, diálogos de
referência e timeline preliminar. Renderização em vídeo fica para a fase de FFmpeg.

## Fluxo de vídeo inicial

Endpoints principais da Fase 6:

```text
POST /api/v1/video/projects/{project_id}/cost-estimate
POST /api/v1/video/projects/{project_id}/clips/generate
GET  /api/v1/video/projects/{project_id}/clips
GET  /api/v1/video/projects/{project_id}/jobs/{job_id}
POST /api/v1/video/projects/{project_id}/clips/{clip_id}/review
```

Os clipes usam o provider de vídeo configurado. Provider `mock` e modelo `mock-video` são
recusados no fluxo da aplicação.

## Fluxo de finalização inicial

Endpoints principais da Fase 7:

```text
POST /api/v1/finalization/projects/{project_id}/timeline/final
POST /api/v1/finalization/projects/{project_id}/exports
```

A finalização monta a timeline final, sintetiza diálogos com voz consistente por
personagem quando o provider de speech está configurado, e grava um manifesto JSON
quando `ffmpeg` não está disponível no PATH ou quando a renderização falha.

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
divergências estruturadas e resume jobs, custos, artefatos obsoletos e score de
qualidade do projeto.
