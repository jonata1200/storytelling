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
