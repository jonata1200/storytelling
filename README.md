# Storytelling Studio

Storytelling Studio é uma aplicação local para criar projetos audiovisuais com apoio de IA.
Ela transforma uma ideia em roteiro, cenas, biblioteca visual e segmentos de vídeo contínuo.

## Recursos

- Criação de projetos por prompt, ideia salva ou briefing.
- Geração de ideias, roteiro, cenas e planos.
- Biblioteca visual de personagens, locais, objetos e referências.
- Vídeo contínuo por segmentos, com revisão e aprovação antes de avançar.
- Continuidade por frame final aprovado como ponto de partida do próximo segmento.
- Storyboard e animatic permanecem como caminho legado para projetos antigos.
- Custos, storage e observabilidade.

## Stack

- Python 3.12
- FastAPI
- NiceGUI
- SQLAlchemy async
- Alembic
- PostgreSQL com pgvector
- Redis
- Ruff, mypy e pytest

## Requisitos

- Python 3.12 ou superior
- Docker Desktop
- Git
- FFmpeg para extração de frames de continuidade

## Instalação

Crie o ambiente virtual:

```powershell
python -m venv .venv
```

Ative o ambiente:

```powershell
.\.venv\Scripts\Activate.ps1
```

Atualize o pip:

```powershell
python -m pip install --upgrade pip
```

Instale as dependências:

```powershell
pip install -r requirements.lock
```

Instale o pacote local:

```powershell
pip install -e . --no-deps
```

Crie o arquivo de ambiente:

```powershell
Copy-Item .env.example .env
```

## Configuração

Configure as chaves no `.env` ou pela tela de Configurações de IA:

```env
TEXT_PROVIDER=ollama_cloud
OLLAMA_CLOUD_API_KEY=sua_chave_ollama
OLLAMA_CLOUD_DEFAULT_MODEL=deepseek-v4-flash:cloud

IMAGE_PROVIDER=google_ai
VIDEO_PROVIDER=google_ai
GOOGLE_AI_API_KEY=sua_chave_google_ai
GOOGLE_AI_IMAGE_MODEL=gemini-3.1-flash-lite-image
GOOGLE_AI_VIDEO_MODEL=veo-3.1-lite-generate-preview
FFMPEG_PATH=C:\caminho\para\ffmpeg.exe

SPEECH_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=sua_chave_elevenlabs
ELEVENLABS_VOICE_ID=voice_id_padrao
```

Variáveis locais mais importantes:

```env
APP_ENV=local
APP_DEBUG=true
APP_SECRET_KEY=change-me-in-development
DATABASE_URL=postgresql+asyncpg://storytelling:storytelling@localhost:5433/storytelling
REDIS_URL=redis://localhost:6379/0
```

## Comandos da Aplicação

Iniciar a aplicação em primeiro plano:

```powershell
.\scripts\story.ps1 run
```

Iniciar em segundo plano:

```powershell
.\scripts\story.ps1 run -Background
```

Iniciar em modo desenvolvimento com reload:

```powershell
.\scripts\story.ps1 run -Dev
```

Parar aplicação, PostgreSQL e Redis:

```powershell
.\scripts\story.ps1 stop
```

Reiniciar tudo:

```powershell
.\scripts\story.ps1 restart
```

Ver status:

```powershell
.\scripts\story.ps1 tools status
```

Ver logs:

```powershell
.\scripts\story.ps1 tools logs
```

Aplicar migrations:

```powershell
.\scripts\story.ps1 tools migrate
```

Rodar testes:

```powershell
.\scripts\story.ps1 tools test
```

> Os testes exigem PostgreSQL e Redis rodando. Antes de executar a suíte, suba a
> infraestrutura com `docker compose up -d` (ou `.\scripts\story.ps1 run`). Sem ela,
> a suíte falha no setup.

Rodar checks completos:

```powershell
.\scripts\story.ps1 tools check
```

Limpar arquivos de runtime:

```powershell
.\scripts\story.ps1 tools clean
```

Executar com bypass de política do PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\story.ps1 run
```

## URLs Locais

Aplicação:

```text
http://127.0.0.1:8000/
```

Health check:

```text
http://127.0.0.1:8000/api/v1/health/live
```

## Verificações

Rodar pytest diretamente:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Rodar Ruff:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
```

Rodar mypy:

```powershell
.\.venv\Scripts\python.exe -m mypy app tests
```

Testes smoke reais ficam desativados por padrão para evitar chamadas pagas. Habilite
somente quando quiser testar provedores externos.

## API Principal

Rota pública:

```text
GET /api/v1/health/live
```

Rotas principais da API:

```text
GET  /api/v1/projects
GET  /api/v1/projects/search
POST /api/v1/storytelling/projects/{project_id}/ideas/generate
POST /api/v1/storytelling/projects/{project_id}/script/generate
POST /api/v1/storytelling/projects/{project_id}/scenes/generate
POST /api/v1/visual-bible/projects/{project_id}/generate
POST /api/v1/storyboards/projects/{project_id}/generate
POST /api/v1/video/projects/{project_id}/clips/generate
GET  /api/v1/observability/projects/{project_id}/summary
GET  /api/v1/storage/usage
GET  /api/v1/costs/projects/{project_id}/summary
```


## Estrutura

```text
app/
  api/               roteadores centrais
  config/            settings, providers e preferências
  costs/             custos e orçamento
  generation/        prompts, modelos e provedores
  jobs/              execução interna de etapas longas
  observability/     eventos e métricas
  projects/          projetos, artefatos e versionamento
  storyboards/       frames, prompts e animatic
  storytelling/      briefing, ideias, roteiro, cenas e planos
  storage/           uso e limpeza local
  ui/                interface NiceGUI
  video_generation/  clipes e revisão
  visual_bible/      personagens, locais, objetos e referências

tests/               suíte automatizada
scripts/             automação local
alembic/             migrations
storage/             arquivos gerados
```

## Observações

- O script principal é `scripts/story.ps1`.
- Etapas longas rodam dentro da própria aplicação.
- Não há dependência de Celery ou worker externo para criar roteiro.
- Scripts antigos seguem como wrappers de compatibilidade: `scripts/app.ps1`,
  `scripts/executar.ps1` e `scripts/finalizar.ps1`.
