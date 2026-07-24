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
pip install -e ".[dev]"
Copy-Item .env.example .env
docker compose up -d
alembic upgrade head
uvicorn app.main:app --reload
```

Depois da primeira configuracao, voce pode usar o script unificado da pasta `scripts`:

```powershell
.\scripts\app.ps1 start
```

Para iniciar a API em segundo plano:

```powershell
.\scripts\app.ps1 start -Background
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
OPENROUTER_DEFAULT_MODEL=openai/gpt-4o-mini
OPENROUTER_IMAGE_MODEL=google/gemini-2.5-flash-image
OPENROUTER_VIDEO_MODEL=google/veo-3.1
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
video. A narracao final mock foi bloqueada; enquanto nao houver provider real de
voz configurado/implementado, essa etapa retorna erro claro para a interface.

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

Credenciais basicas iniciais:

```text
usuario: admin
senha: admin
```

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
- Narracao final bloqueada ate provider real de voz, legendas SRT, timeline final
  e export manifest.
- Continuity Ledger, quality gate, varredura inicial de seguranca e correlation
  ID por requisicao.
- Testes de health, auth, maquina de estados, dependencias, custos e mock LLM.

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

A geracao de narracao final mock esta bloqueada ate existir provider real de
voz. As legendas sao geradas em SRT e a exportacao grava um manifesto JSON
quando `ffmpeg` nao esta disponivel no PATH.

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
