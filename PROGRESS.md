# Progress

## Fase 1 - Fundacao

Status: concluida

Concluido:

- Estrutura inicial do repositorio.
- Configuracao por `.env`.
- Docker Compose com PostgreSQL pgvector e Redis.
- FastAPI com roteador versionado.
- NiceGUI inicial montada no FastAPI.
- SQLAlchemy 2 async.
- Alembic com migracao inicial.
- Celery configurado com Redis.
- Health check `live` e `ready`.
- Autenticacao HTTP Basic inicial.
- Dominio minimo de projetos, versoes, artefatos e aprovacoes.
- Testes basicos de health e auth.
- Ambiente virtual `.venv` criado localmente.
- Verificacoes executadas:
  - `pytest`: 3 testes passaram.
  - `ruff check .`: passou.
  - `mypy app tests`: passou.
  - `python -m alembic history`: leu a migracao inicial.
  - import do ASGI app completo: passou.
  - `uvicorn app.main:app`: subiu corretamente em primeiro plano.

Observacoes:

- Docker Desktop esta instalado, mas o comando `docker` ainda nao aparece no PATH
  normal do terminal. O caminho completo funciona:
  `C:\Program Files\Docker\Docker\resources\bin\docker.exe`.

## Fase 2 - Dominio

Status: base concluida

Concluido:

- Repositorio inicial de projetos e artefatos.
- Maquina de estados do projeto com transicoes validas.
- Versionamento incremental de artefatos.
- Aprovacoes humanas com decisao, notas e bloqueio de artefato.
- Grafo de dependencias entre artefatos.
- Invalidacao transitiva de dependentes como `STALE`.
- Respeito a artefatos bloqueados durante invalidacao automatica.
- Modelos de assets e versoes de assets.
- Registro e estimativa de custos.
- Endpoints para status, versoes, aprovacoes, dependencias, assets e custos.
- Migracao `202607160002_phase2_domain`.
- PostgreSQL e Redis subidos via Docker Compose.
- `alembic upgrade head` executado com sucesso.
- `/api/v1/health/ready` validado contra PostgreSQL e Redis reais.
- Verificacoes executadas:
  - `pytest`: 9 testes passaram.
  - `ruff check .`: passou.
  - `mypy app tests`: passou.

## Fase 3 - Narrativa

Status: base concluida

Concluido:

- Contrato `LLMProvider`.
- `MockLLMProvider` deterministico.
- Templates de prompt versionaveis.
- Registro de execucoes de prompt com provider, modelo, prompt, variaveis,
  resposta, custo estimado e duracao.
- Entidades de briefing, ideias, Story Bible, roteiro, versoes de roteiro,
  cenas e planos.
- Endpoints para criar briefing e gerar ideias, Story Bible, roteiro, cenas e
  planos.
- Artefatos narrativos ligados ao `Artifact` versionado.
- Dependencias criadas entre briefing, ideias, Story Bible, roteiro, cenas e
  planos.
- Migracao `202607160003_phase3_storytelling`.
- `alembic upgrade head` executado com sucesso.
- Smoke test de fluxo narrativo executado contra PostgreSQL:
  - projeto criado;
  - briefing criado;
  - 3 ideias geradas;
  - Story Bible gerada;
  - roteiro gerado;
  - 4 cenas geradas com planos.
- Verificacoes executadas:
  - `pytest`: 12 testes passaram.
  - `ruff check .`: passou.
  - `mypy app tests`: passou.

Observacao:

- O smoke test via `TestClient` com multiplas chamadas de banco encontrou uma
  limitacao de pool/event loop do `asyncpg`; o fluxo foi validado diretamente
  pelos services async no mesmo loop. Em servidor ASGI real isso nao deve ser o
  caminho comum, mas vamos criar testes de integracao async dedicados quando
  adicionarmos fixture de banco.

Proximo:

- Fase 4: personagens, locais, objetos, fichas canonicas, referencias visuais,
  consistencia e provider mock/configuravel de imagem.
