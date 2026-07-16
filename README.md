# Storytelling Studio

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
pytest
ruff check .
mypy app tests
```

Os testes automatizados nao devem chamar APIs pagas. Providers externos entram por
interfaces e devem ter mocks por padrao.

## Estado atual

Fase 1 e base da Fase 2 estao implementadas:

- API FastAPI com UI NiceGUI inicial.
- PostgreSQL, pgvector e Redis via Docker Compose.
- Alembic async usando `asyncpg`.
- Projetos, versoes, artefatos, aprovacoes, dependencias, assets e custos.
- Maquina de estados inicial para o pipeline de projeto.
- Briefing, ideias, Story Bible, roteiro, cenas e planos com provider mock.
- Templates e execucoes de prompt auditaveis.
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

Todas as geracoes da Fase 3 usam `MockLLMProvider` por padrao e nao consomem
APIs pagas.
