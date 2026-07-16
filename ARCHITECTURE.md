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
- `app/generation`: templates de prompt e auditoria de execucoes.
- `app/providers`: contratos e providers substituiveis.
- `app/storytelling`: briefing, ideias, Story Bible, roteiro, cenas e planos.
- `app/storyboards`: quadros de storyboard, narracao provisoria, animatic e
  timeline preliminar.
- `app/visual_bible`: personagens, locais, objetos, fichas canonicas e
  referencias visuais.
- `app/video_generation`: providers de video, jobs, clipes e revisao humana.
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
- A Fase 3 usa um `MockLLMProvider` deterministico para validar fluxo, dados e
  auditoria antes de integrar APIs pagas.
- A Fase 4 usa um `MockImageProvider` que grava SVG local. Ele exercita assets,
  prompts, provider substituivel e consistencia sem custo externo.
- A Fase 5 gera storyboards a partir dos planos, nunca diretamente do roteiro
  inteiro. O animatic inicial e um manifesto JSON; renderizacao real entra depois.
- A Fase 6 registra jobs de geracao de video no banco e usa provider mock por
  padrao. Celery pode executar esses jobs de forma assincrona nas proximas
  iteracoes sem mudar o contrato de dominio.

## Evolucao prevista

A Fase 7 deve introduzir voz, legendas, musica, efeitos, timeline final,
integracao FFmpeg e exportacao MP4/SRT.
