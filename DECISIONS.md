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
