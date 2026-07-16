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

## Fase 4 - Biblia visual

Status: base concluida

Concluido:

- Contrato `ImageProvider`.
- `MockImageProvider` que gera SVG local sem custo externo.
- Entidades de personagens, versoes de personagem, locais, versoes de local,
  objetos, versoes de objeto e referencias visuais.
- `character_fingerprint` com hash da ficha canonica e prompt canonico.
- Geracao de Biblia Visual a partir da Story Bible.
- Criacao de `Artifact` versionado para personagens, locais, objetos e
  referencias visuais.
- Criacao de `Asset` e `AssetVersion` para referencias visuais.
- Registro de execucao de prompt para geracao de imagem mockada.
- Dependencias entre Story Bible, entidades visuais e referencias.
- Checagem inicial de consistencia visual por vistas obrigatorias.
- Endpoints de Biblia Visual, listas canonicas, geracao de referencias e
  consistencia.
- Migracao `202607160004_phase4_visual_bible`.
- `alembic upgrade head` executado com sucesso.
- Smoke test visual executado contra PostgreSQL:
  - 1 personagem criado;
  - 1 local criado;
  - 1 objeto criado;
  - 2 referencias visuais mockadas geradas;
  - checagem apontou vistas restantes ausentes.
- Verificacoes executadas:
  - `pytest`: 14 testes passaram.
  - `ruff check .`: passou.
  - `mypy app tests`: passou.

## Fase 5 - Storyboard

Status: base concluida

Concluido:

- Entidades de `StoryboardFrame`, `AudioTrack`, `Animatic`, `Timeline` e
  `TimelineItem`.
- Storyboards gerados a partir de `Shot`.
- Quadros de storyboard gerados com `MockImageProvider`.
- Assets de storyboard gravados fora do banco.
- Registro de prompt/provider/modelo para cada quadro.
- Narração provisoria com transcript e alinhamento aproximado por palavra.
- Animatic preliminar como manifesto JSON.
- Timeline preliminar 9:16 com camada visual e camada de audio.
- Dependencias entre planos, storyboard, narracao, animatic e timeline.
- Endpoints de geracao/listagem de storyboard e geracao de animatic.
- Migracao `202607160005_phase5_storyboards`.
- `alembic upgrade head` executado com sucesso.
- Smoke test storyboard executado contra PostgreSQL:
  - 4 cenas;
  - 12 quadros de storyboard;
  - narração provisoria de 240 segundos;
  - animatic de 240 segundos;
  - timeline com 13 itens.
- Verificacoes executadas:
  - `pytest`: 16 testes passaram.
  - `ruff check .`: passou.
  - `mypy app tests`: passou.

## Fase 6 - Video

Status: base concluida

Concluido:

- Contrato `VideoProvider`.
- `ProviderCapabilities` para selecionar providers por recursos.
- `MockVideoProvider` com text-to-video e image-to-video simulados.
- Entidades de `GenerationJob`, `VideoClip` e `ClipReview`.
- Idempotencia por storyboard frame, variante, provider e modelo.
- Status, progresso, tentativas, erro, custo estimado e payload de job.
- Backoff exponencial para retentativas.
- Geracao de clipes mockados a partir de storyboard frames.
- Assets de video mockado fora do banco.
- Registro de custo estimado por clipe.
- Revisao humana de clipes com aprovacao, rejeicao ou regeneracao.
- Endpoints de estimativa de custo, geracao de clipes, listagem, status de job
  e revisao.
- Migracao `202607160006_phase6_video_generation`.
- `alembic upgrade head` executado com sucesso.
- Smoke test de video executado contra PostgreSQL:
  - 12 frames de storyboard;
  - 2 jobs de video;
  - 2 clipes gerados;
  - job `SUCCEEDED`;
  - revisao `APPROVED`.
- Verificacoes executadas:
  - `pytest`: 19 testes passaram.
  - `ruff check .`: passou.
  - `mypy app tests`: passou.

Proximo:

- Fase 7: voz, legendas, musica, efeitos, timeline final, FFmpeg e exportacao.
