# Decisions

## ADR-0001: Modular monolith primeiro

Status: Accepted

Comecaremos com um monolito modular em Python. Isso reduz custo operacional,
facilita testes e evita distribuicao prematura. Os modulos serao separados por
dominio para permitir extracao futura se houver necessidade real.

## ADR-0002: Docker para dependencias de infraestrutura

Status: Accepted

PostgreSQL, pgvector e Redis rodam via Docker Compose no desenvolvimento local.
Isso aproxima o ambiente local do futuro SaaS sem exigir instalacoes manuais de
banco e fila no Windows.

## ADR-0003: Providers mockados por padrao no inicio

Status: Accepted

Nenhum teste automatizado deve consumir APIs pagas. As integracoes reais serao
adicionadas atras de interfaces e substituidas por mocks nos testes.

## ADR-0004: Versionamento desde o primeiro dominio

Status: Accepted

Projetos e artefatos ja nascem com versoes. Isso evita reescrever o modelo quando
aprovacoes, comparacoes e restauracao de versoes forem implementadas.

## ADR-0005: Alembic com asyncpg

Status: Accepted

As migracoes usam `asyncpg`, o mesmo driver da aplicacao. Isso evita instalar
`psycopg2` apenas para Alembic e mantem a configuracao de banco em uma unica URL.

## ADR-0006: Invalidation por grafo explicito

Status: Accepted

Dependencias entre artefatos sao persistidas como arestas explicitas. Quando um
artefato muda, apenas dependentes transitivos nao bloqueados sao marcados como
`STALE`.

## ADR-0007: Narrativa concreta mais Artifact generico

Status: Accepted

Briefing, ideias, Story Bible, roteiro, cenas e planos possuem tabelas proprias
para consulta e fluxo de produto, mas tambem sao salvos como `Artifact`
versionado. Isso preserva auditoria, aprovacao, dependencia e invalidacao em um
modelo comum.

## ADR-0008: Provider mock como primeira integracao LLM

Status: Accepted

A Fase 3 usa um provider mock deterministico para gerar estruturas narrativas.
Isso permite desenvolver o pipeline e os testes sem custos, sem instabilidade de
API externa e sem acoplar o dominio a um modelo especifico.

## ADR-0009: Referencias visuais como Asset mais VisualReference

Status: Accepted

Referencias visuais sao rastreadas em uma tabela propria (`VisualReference`) e o
arquivo gerado fica em `Asset`. O PostgreSQL guarda metadados, caminho e hash,
mas nao armazena o arquivo pesado.

## ADR-0010: MockImageProvider gera SVG local

Status: Accepted

Na Fase 4, o provider de imagem mockado gera SVGs locais deterministicas. Isso
mantem o fluxo funcional sem APIs pagas e prepara o contrato para providers reais
de imagem nas fases seguintes.

## ADR-0011: Storyboard sempre deriva de Shot

Status: Accepted

Quadros de storyboard sao gerados a partir de planos (`Shot`), nao diretamente
do roteiro completo. Isso preserva duracao, acao, emocao, camera e dependencias
por plano.

## ADR-0012: Animatic inicial como manifesto JSON

Status: Accepted

Na Fase 5, o animatic e um manifesto estruturado com quadros, duracoes, narracao
provisoria e timeline preliminar. Isso valida o fluxo antes de introduzir FFmpeg
e renderizacao real nas fases posteriores.

## ADR-0013: Jobs de video persistidos antes de Celery completo

Status: Accepted

Jobs de geracao sao registrados no banco com status, tentativas, payload,
provider, custo e idempotencia. A execucao da Fase 6 ainda e sincrona com provider
mockado, mas o modelo ja permite mover a execucao para Celery sem mudar a API.

## ADR-0014: MockVideoProvider gera manifesto de clipe

Status: Accepted

O provider de video mockado grava arquivos `.mockvideo.json`, representando o
clipe gerado. Isso exercita jobs, assets, custos e revisao humana sem chamar APIs
pagas.

## ADR-0015: MockSpeechProvider como primeira camada de voz

Status: Accepted

A Fase 7 usa um provider de voz mockado que grava WAV silencioso local e produz
alinhamento por palavra. Isso permite gerar legendas, dependencias, assets e
timeline final sem depender de um servico pago de TTS.

## ADR-0016: Exportacao cai para manifesto quando FFmpeg falta

Status: Accepted

Quando `ffmpeg` nao esta disponivel no PATH, a exportacao grava um manifesto JSON
com timeline, legenda e perfil 9:16. Esse fallback mantem o fluxo testavel no
Windows local e deixa claro onde a renderizacao MP4 real sera conectada.

## ADR-0017: Qualidade como modulo separado do pipeline criativo

Status: Accepted

Continuity Ledger, alertas, security scan e metricas ficam em `app/quality`, sem
misturar regras de controle com os services de narrativa, visual, video ou
finalizacao. Isso permite rodar qualidade sob demanda, aceitar divergencias
intencionais e evoluir checks sem alterar os providers.

## ADR-0018: Correlation ID em middleware HTTP

Status: Accepted

Cada requisicao recebe ou propaga `x-correlation-id`. A implementacao inicial
adiciona tambem `x-process-time-ms`, preparando logs estruturados e rastreamento
mais completo sem criar dependencia de uma stack externa de observabilidade.

## ADR-0019: OpenRouter por HTTP e fallback mock

Status: Accepted

O OpenRouter e integrado por HTTP usando o endpoint compativel com Chat
Completions, sem SDK externo no dominio. A selecao de modelo fica persistida por
projeto e tarefa em `project_model_settings`. Quando `OPENROUTER_API_KEY` nao
esta configurada, a aplicacao cai automaticamente para `MockLLMProvider`.
