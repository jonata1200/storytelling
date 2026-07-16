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
