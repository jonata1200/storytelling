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
