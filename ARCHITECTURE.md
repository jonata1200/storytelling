# Architecture

Storytelling Studio comeca como um modular monolith em Python.

## Camadas

- `app/api`: rotas HTTP, validacao de entrada e dependencias.
- `app/ui`: telas NiceGUI.
- `app/config`: configuracao por ambiente.
- `app/database`: engine, sessoes e base declarativa.
- `app/auth`: autenticacao inicial.
- `app/projects`: dominio inicial de projetos, versoes, artefatos e aprovacoes.
- `app/workflows`: maquina de estados e grafo de dependencias.
- `app/assets`: metadados e versoes de arquivos armazenados fora do banco.
- `app/costs`: estimativas e registros de custo.
- `app/workers`: Celery e tarefas em background.

## Decisoes estruturais

- FastAPI hospeda a API e a UI NiceGUI no mesmo processo durante o MVP local.
- PostgreSQL e Redis rodam via Docker Compose.
- SQLAlchemy 2 e Alembic cuidam da persistencia e das migracoes.
- UUIDs, timestamps e soft delete sao padrao para entidades principais.
- Toda geracao futura deve salvar prompt, provider, parametros, custo e resultado.
- Providers de IA ficarao atras de interfaces, nunca dentro do dominio.
- Migrações usam Alembic com engine async para manter um unico driver PostgreSQL:
  `asyncpg`.

## Evolucao prevista

A Fase 3 introduz briefing, ideias, Story Bible, roteiro, templates de prompt e
provider mock de linguagem. Esses artefatos devem usar o versionamento e o grafo
de dependencias ja criados.
