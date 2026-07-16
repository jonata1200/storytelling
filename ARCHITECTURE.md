# Architecture

Storytelling Studio comeca como um modular monolith em Python.

## Camadas

- `app/api`: rotas HTTP, validacao de entrada e dependencias.
- `app/ui`: telas NiceGUI.
- `app/config`: configuracao por ambiente.
- `app/database`: engine, sessoes e base declarativa.
- `app/auth`: autenticacao inicial.
- `app/projects`: dominio inicial de projetos, versoes, artefatos e aprovacoes.
- `app/workers`: Celery e tarefas em background.

## Decisoes estruturais

- FastAPI hospeda a API e a UI NiceGUI no mesmo processo durante o MVP local.
- PostgreSQL e Redis rodam via Docker Compose.
- SQLAlchemy 2 e Alembic cuidam da persistencia e das migracoes.
- UUIDs, timestamps e soft delete sao padrao para entidades principais.
- Toda geracao futura deve salvar prompt, provider, parametros, custo e resultado.
- Providers de IA ficarao atras de interfaces, nunca dentro do dominio.

## Evolucao prevista

A Fase 2 deve ampliar o dominio com maquina de estados, grafo de dependencias,
custos, assets e auditoria. A Fase 3 introduz briefing, ideias, Story Bible,
roteiro e provider mock de linguagem.
