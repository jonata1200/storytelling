# Storytelling

Storytelling é uma aplicação local para criar projetos audiovisuais com apoio de IA.
Ela transforma uma ideia em roteiro, cenas, biblioteca visual e pacotes de vídeo prontos
para produção.

## Recursos

- Criação de projetos por prompt, ideia salva ou briefing.
- Geração de ideias, roteiro, cenas e planos.
- Biblioteca visual de personagens, locais, objetos e referências, com imagens
  geradas por automação do navegador no Meta AI (perfis autenticados locais).
- Geração automática de vídeo por segmento no Vibes.ai (automação de navegador):
  prompt, frame inicial e frame final por segmento, com continuidade via frame
  final do segmento anterior.
- QA automático dos vídeos gerados (análise multimodal via Ollama Cloud) com
  rejeição objetiva e regeneração automática opcional.
- Finalização: seleção de variantes por segmento e empacotamento do resultado.
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

Instale as dependências (runtime + desenvolvimento):

```powershell
pip install -r requirements.lock -r requirements.dev.lock
```

Para um ambiente de produção sem ferramentas de dev (pytest, mypy, ruff), instale
apenas `requirements.lock`.

Instale o pacote local:

```powershell
pip install -e . --no-deps
```

Crie o arquivo de ambiente:

```powershell
Copy-Item .env.example .env
```

## Imagens Docker (PostgreSQL e Redis)

A infraestrutura local usa duas imagens do Docker Hub, definidas no
`docker-compose.yml`:

| Serviço  | Imagem                 |
|----------|------------------------|
| postgres | pgvector/pgvector:pg16 |
| redis    | redis:7-alpine         |

> **Senhas padrão**: o `docker-compose.yml` usa `POSTGRES_USER=storytelling` e
> `POSTGRES_PASSWORD=storytelling` como padrões de conveniência para desenvolvimento
> local (as portas ficam restritas a `127.0.0.1`). Se for expor os containers a
> qualquer outra interface de rede, defina `POSTGRES_PASSWORD` (e
> `DATABASE_URL` correspondente) com um valor próprio antes de subir o compose.

Na primeira execução, `\scripts\story.ps1 run` (ou `docker compose up -d`)
baixa as imagens automaticamente. Para baixá-las antecipadamente:

```powershell
docker pull redis:7-alpine
docker pull pgvector/pgvector:pg16
```

Confira se já estão disponíveis localmente:

```powershell
docker images
```

> **Falha ao baixar com "TLS handshake timeout"**: se o download travar com
> `net/http: TLS handshake timeout` ao acessar `production.cloudfront.docker.com`,
> normalmente o serviço interno de proxy de downloads do Docker Desktop
> (`hubproxy`) ficou pendurado — não é a sua conexão. Para corrigir:
>
> 1. Encerre o Docker Desktop pela bandeja do sistema (ícone do Docker →
>    **Quit Docker Desktop**) e reabra.
> 2. Tente baixar novamente:
>
>    ```powershell
>    docker pull pgvector/pgvector:pg16
>    docker pull redis:7-alpine
>    ```
>
> 3. Suba a infraestrutura e confirme os containers saudáveis:
>
>    ```powershell
>    docker compose up -d
>    docker compose ps
>    ```
>
> Se o problema se repetir, revise **Settings → Resources → Proxies** no Docker
> Desktop: o Docker Desktop detecta automaticamente proxies do Windows, mesmo
> quando desativados (por exemplo, restos de ferramentas como Clash/V2Ray
> deixam o endereço configurado no registro), e roteia os downloads por um
> endereço inacessível.

## Configuração

Configure as chaves no `.env` ou pela tela de Configurações de IA:

```env
TEXT_PROVIDER=ollama_cloud
OLLAMA_CLOUD_INTEGRATION_MODE=api
OLLAMA_API_KEY=sua_chave_ollama
OLLAMA_CLOUD_BASE_URL=https://ollama.com/api
OLLAMA_CLOUD_DEFAULT_MODEL=gemma4:31b-cloud
OLLAMA_CLOUD_VISION_MODEL=gemma3
IMAGE_PROVIDER=meta
META_IMAGE_INTEGRATION_MODE=browser
META_IMAGE_MODEL=muse-image
META_BROWSER_PROFILE_PATH=./runtime/browser_profiles/meta
META_BROWSER_AUTOMATION_ENABLED=false

VIDEO_PROVIDER=vibes
VIBES_INTEGRATION_MODE=browser
VIBES_VIDEO_MODEL=vibes
VIBES_BROWSER_PROFILE_PATH=./runtime/browser_profiles/meta
VIBES_BROWSER_AUTOMATION_ENABLED=false # habilite só após instalar/autorizar o backend browser
FFMPEG_PATH=C:\caminho\para\ffmpeg.exe
```

FFmpeg: se `FFMPEG_PATH` ficar vazio, a aplicação usa o executável embutido do
pacote `imageio-ffmpeg`, depois procura `ffmpeg` no PATH e por fim caminhos
comuns do Windows. Quando um caminho configurado não resolve para um
executável, um warning é registrado no log. Use `FFMPEG_PATH` apenas quando
precisar de uma versão de sistema diferente da embutida.

Variáveis locais mais importantes:

```env
APP_ENV=local
APP_DEBUG=true
APP_SECRET_KEY=change-me-in-development
# Token de autenticação dos endpoints privados. Obrigatório fora de
# local/development/test (a aplicação recusa iniciar sem ele) e exigido
# sempre que o bind de rede não for 127.0.0.1. Em local, deixar vazio
# desativa a auth — qualquer processo na máquina poderá chamar a API.
APP_API_TOKEN=
DATABASE_URL=postgresql+asyncpg://storytelling:storytelling@localhost:5433/storytelling
REDIS_URL=redis://localhost:6379/0
QA_OLLAMA_MULTIMODAL_ENABLED=true
QA_AUTO_REJECT_OBJECTIVE_FAILURES=true
SHOT_AUTO_REGENERATION_ENABLED=true
SHOT_AUTO_REGENERATION_MAX_ATTEMPTS=2
```

## Comandos da Aplicação

Iniciar a aplicação em primeiro plano:

```powershell
.\scripts\story.ps1 run
```

O `story.ps1` inicia automaticamente o worker local de mídia/QA, obrigatório para Meta
Image e Vibes. Para executá-lo manualmente, use:

```powershell
.\.venv\Scripts\storytelling-worker.exe
```

O worker usa PostgreSQL como fonte de verdade e Redis Streams somente para despacho.
Reiniciar o FastAPI não cancela jobs já persistidos ou submetidos ao provider. O script
`story.ps1` inicia esse worker diretamente no Windows para que a automação de navegador use
os perfis autenticados locais. O worker recupera jobs órfãos, retoma polling quando há um
external ID persistido e mantém browser automation fora do processo FastAPI.

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
POST /api/v1/storytelling/projects/{project_id}/script/hooks
POST /api/v1/storytelling/projects/{project_id}/script/generate
POST /api/v1/storytelling/projects/{project_id}/scenes/generate
POST /api/v1/visual-bible/projects/{project_id}/generate
POST /api/v1/storyboards/projects/{project_id}/generate
POST /api/v1/video/projects/{project_id}/continuous/plan
POST /api/v1/video/projects/{project_id}/continuous/prepare
GET  /api/v1/video/projects/{project_id}/continuous/segments
PATCH /api/v1/video/projects/{project_id}/continuous/segments/{segment_id}
POST /api/v1/video/projects/{project_id}/continuous/segments/{segment_id}/done
POST /api/v1/video/projects/{project_id}/continuous/segments/{segment_id}/reject
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
  video_generation/  pacote de produção de vídeo
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
