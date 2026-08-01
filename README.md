# Storytelling Studio

Storytelling Studio é uma aplicação para criar, organizar e produzir histórias
cinematográficas com apoio de IA. O produto foi desenhado para transformar uma
ideia inicial em um projeto completo de vídeo vertical, passando por roteiro,
cenas, personagens, referências visuais, storyboard, clipes, montagem,
exportação e controle de qualidade.

A proposta da aplicação é funcionar como um estúdio de produção guiado: a IA
acelera as etapas criativas e operacionais, enquanto o usuário mantém revisão,
aprovação e controle sobre o resultado.

## Principais Recursos

- Geração de ideias narrativas com filtros e busca.
- Criação de projetos a partir de prompt, ideia salva ou briefing estruturado.
- Geração de roteiro inicial com execução interna da aplicação, sem worker
  externo.
- Divisão do roteiro em cenas e planos.
- Biblioteca visual para personagens, locais, objetos e referências.
- Storyboard com frames, prompts visuais e animatic.
- Geração e revisão de clipes de vídeo.
- Timeline final, exportação e manifesto quando renderização não estiver
  disponível.
- Controle de custos, orçamento por projeto e estimativas por operação.
- Observabilidade por projeto com eventos, execuções de prompt e readiness.
- Autenticação local, sessões persistidas, CSRF e modo de usuário único.
- Storage local auditável, reconciliação e limpeza de arquivos órfãos.

## Fluxo Da Aplicação

1. O usuário descreve uma ideia ou escolhe uma ideia já gerada.
2. A aplicação cria o projeto com briefing, formato e modelos de produção.
3. A IA gera o roteiro e, em seguida, cenas e planos.
4. O usuário revisa personagens, locais, objetos e referências visuais.
5. A aplicação monta storyboard, animatic e prompts de vídeo.
6. Os clipes são gerados, revisados e encaminhados para montagem.
7. A timeline final é exportada ou registrada como manifesto.
8. O controle de qualidade consolida continuidade, custos, eventos e pendências.

## Stack Técnica

- Python 3.12
- FastAPI
- NiceGUI
- SQLAlchemy async
- Alembic
- PostgreSQL com pgvector
- Redis
- Pydantic Settings
- Ruff, mypy e pytest

## Provedor De IA

Texto pode usar `nvidia_nim` ou `ollama_cloud` por API. Imagem e video podem usar
`google_ai` pela Gemini API ou o provider experimental `veo_ai_free`. Voz dos
personagens e dublagem final usam `elevenlabs`. Os modelos padrao ficam no `.env`:

```env
AI_PROVIDER=nvidia_nim
TEXT_PROVIDER=ollama_cloud
TEXT_PROVIDER_FALLBACKS=nvidia_nim
IMAGE_PROVIDER=google_ai
VIDEO_PROVIDER=google_ai
SPEECH_PROVIDER=elevenlabs
DUBBING_PROVIDER=elevenlabs

NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_NIM_API_KEY=sua_chave_nvidia
NVIDIA_NIM_DEFAULT_MODEL=z-ai/glm-5.2

OLLAMA_CLOUD_BASE_URL=https://ollama.com/api
OLLAMA_CLOUD_API_KEY=sua_chave_ollama
OLLAMA_CLOUD_DEFAULT_MODEL=gpt-oss:120b

GOOGLE_AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
GOOGLE_AI_API_KEY=sua_chave_google_ai
GOOGLE_AI_IMAGE_MODEL=gemini-3.1-flash-image
GOOGLE_AI_IMAGE_SIZE=1K
GOOGLE_AI_VIDEO_MODEL=veo-3.1-generate-preview
GOOGLE_AI_VIDEO_FAST_MODEL=veo-3.1-fast-generate-preview
GOOGLE_AI_VIDEO_DEFAULT_DURATION_SECONDS=8
GOOGLE_AI_VIDEO_POLL_INTERVAL_SECONDS=10
GOOGLE_AI_VIDEO_POLL_TIMEOUT_SECONDS=900

VEO_AI_FREE_ENABLED=false
VEO_AI_FREE_SESSION_PATH=.runtime/veo_free/session.json
VEO_AI_FREE_IMAGE_MODEL=veo-ai-free/image
VEO_AI_FREE_VIDEO_MODEL=veo-ai-free/video

ELEVENLABS_BASE_URL=https://api.elevenlabs.io/v1
ELEVENLABS_API_KEY=sua_chave_elevenlabs
ELEVENLABS_VOICE_ID=voice_id_padrao
ELEVENLABS_SPEECH_MODEL=eleven_multilingual_v2
ELEVENLABS_OUTPUT_FORMAT=mp3_44100_128
DUBBING_SOURCE_LANG=pt
DUBBING_TARGET_LANG=en
DUBBING_POLL_INTERVAL_SECONDS=10
DUBBING_POLL_TIMEOUT_SECONDS=900
```

As chaves e modelos tambem podem ser salvos pela tela de Configuracoes de IA em
`.runtime/preferences.json`.

## Requisitos Locais

- Python 3.12 ou superior
- Docker Desktop
- Git
- FFmpeg opcional para exportação/renderização de vídeo

## Instalação

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.lock
pip install -e . --no-deps
Copy-Item .env.example .env
```

Configure `OLLAMA_CLOUD_API_KEY` ou `NVIDIA_NIM_API_KEY` para texto e
`GOOGLE_AI_API_KEY` para imagem/video. Para voz e dublagem, configure
`ELEVENLABS_API_KEY` e `ELEVENLABS_VOICE_ID` pela tela de Configurações de IA
ou pelo `.env`. O Veo AI Free continua disponivel como fallback experimental local.

## Executando

O script principal fica em `scripts/story.ps1`. Para o uso diário, use apenas
três comandos:

```powershell
.\scripts\story.ps1 run
.\scripts\story.ps1 stop
.\scripts\story.ps1 restart
```

`run` inicia PostgreSQL, Redis, aplica migrations e sobe a aplicação em
primeiro plano. Logs e erros ficam visíveis no terminal, o que facilita debug.
Para finalizar, pressione `Ctrl+C`.

Para executar em segundo plano:

```powershell
.\scripts\story.ps1 run -Background
```

Para desenvolver com reload automático:

```powershell
.\scripts\story.ps1 run -Dev
```

Comandos técnicos ficam em `tools`:

```powershell
.\scripts\story.ps1 tools status
.\scripts\story.ps1 tools logs
.\scripts\story.ps1 tools check
.\scripts\story.ps1 tools test
.\scripts\story.ps1 tools clean
```

Scripts antigos continuam disponíveis como wrappers de compatibilidade:

```powershell
.\scripts\app.ps1 up
.\scripts\executar.ps1
.\scripts\finalizar.ps1
```

URL local:

```text
http://127.0.0.1:8000/
```

Health check:

```text
http://127.0.0.1:8000/api/v1/health/live
```

Se o PowerShell bloquear scripts locais:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\story.ps1 run
```

## Configuração Importante

Variáveis principais:

```env
APP_ENV=local
APP_DEBUG=true
APP_SECRET_KEY=change-me-in-development
DATABASE_URL=postgresql+asyncpg://storytelling:storytelling@localhost:5432/storytelling
REDIS_URL=redis://localhost:6379/0
ALLOW_USER_REGISTRATION=true
SINGLE_USER_MODE=true
MAX_UPLOAD_BYTES=26214400
MAX_GENERATED_ASSET_BYTES=786432000
```

Para produção, use valores seguros:

```env
APP_ENV=production
APP_DEBUG=false
APP_SECRET_KEY=gere-um-segredo-longo-e-unico
ALLOW_USER_REGISTRATION=false
NVIDIA_NIM_API_KEY=sua_chave_no_ambiente
```

## API Principal

Rotas públicas:

```text
GET /api/v1/health/live
```

Rotas autenticadas principais:

```text
GET  /api/v1/projects
GET  /api/v1/projects/search
POST /api/v1/storytelling/projects/{project_id}/ideas/generate
GET  /api/v1/storytelling/projects/{project_id}/ideas/search
POST /api/v1/storytelling/projects/{project_id}/script/generate
POST /api/v1/storytelling/projects/{project_id}/scenes/generate
POST /api/v1/visual-bible/projects/{project_id}/generate
POST /api/v1/storyboards/projects/{project_id}/generate
POST /api/v1/video/projects/{project_id}/clips/generate
POST /api/v1/finalization/projects/{project_id}/exports
POST /api/v1/quality/projects/{project_id}/checks/run
GET  /api/v1/observability/projects/{project_id}/summary
GET  /api/v1/storage/usage
GET  /api/v1/costs/projects/{project_id}/summary
```

Em `APP_ENV=local` e `APP_ENV=test`, a aplicação usa bypass local para facilitar
desenvolvimento. Fora desses ambientes, as rotas operacionais exigem sessão ou
token bearer.

## Qualidade E Desenvolvimento

Comandos recomendados antes de entregar alterações:

```powershell
ruff check app tests
mypy app tests
pytest -q
```

Testes automatizados não devem chamar provedores pagos. Testes smoke reais devem
ser habilitados explicitamente por variáveis como `RUN_PROVIDER_SMOKE_TESTS=1`.

## Estrutura Do Projeto

```text
app/
  api/               roteadores centrais
  auth/              login, cadastro, sessão e CSRF
  config/            settings, providers e preferências
  costs/             estimativas, políticas e orçamento
  finalization/      timeline e exportação
  generation/        prompts, modelos e provedores
  jobs/              execução interna de etapas longas
  observability/     eventos, readiness e métricas
  projects/          projetos, artefatos e versionamento
  quality/           continuidade e checks de qualidade
  storyboards/       frames, prompts e animatic
  storytelling/      briefing, ideias, roteiro, cenas e planos
  storage/           uso, reconciliação e limpeza local
  ui/                interface NiceGUI
  video_generation/  clipes, jobs e revisão
  visual_bible/      personagens, locais, objetos e referências
tests/               suíte automatizada
scripts/             automação local de execução, status, logs e checks
alembic/             migrations do banco
storage/             arquivos gerados localmente
```

## Estado Atual

O projeto está em uma base funcional para desenvolvimento local: criação de
projetos, geracao narrativa com Ollama/Groq/NVIDIA NIM, busca em ideias/projetos, fluxo
visual, storyboard, vídeo, custos, storage, autenticação e observabilidade.

Etapas longas rodam dentro da própria aplicação. Não há dependência de Celery ou
worker externo para criar roteiro.
