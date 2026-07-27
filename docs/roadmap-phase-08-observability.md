# Fase 8 - Observabilidade, Auditoria e Experiencia Operacional

## Objetivo

Facilitar diagnostico de falhas e acompanhamento de producao.

## Escopo

- Adicionar logs estruturados com correlation ID em services e providers.
- Persistir eventos de pipeline por projeto.
- Expor linha do tempo operacional: quem disparou, quando, modelo usado, custo, erro.
- Melhorar mensagens de erro para usuario sem vazar detalhes sensiveis.
- Adicionar dashboard tecnico de readiness: banco, Redis, OpenRouter, FFmpeg, worker.

## Checklist de acoes

- [x] Mapear pontos principais de falha por etapa.
- [x] Padronizar logs estruturados nos services.
- [ ] Padronizar logs estruturados nos providers.
- [x] Propagar correlation ID em chamadas internas relevantes.
- [x] Criar modelo de evento operacional por projeto.
- [ ] Persistir eventos de job: queued, started, progress, succeeded, failed e cancelled.
- [x] Registrar modelo/provider usado em cada evento de IA.
- [x] Registrar custo estimado e real nos eventos relevantes.
- [x] Redigir segredos em logs e mensagens de erro.
- [x] Criar resumo operacional por projeto.
- [x] Criar dashboard de readiness.
- [x] Separar readiness de API, banco, Redis, worker, FFmpeg e OpenRouter.
- [x] Adicionar testes de redacao de segredos.
- [x] Adicionar testes de emissao de eventos.

## Implementado

- `operational_events` foi adicionado via Alembic para registrar eventos por projeto com
  artifact/job, provider/modelo, custo estimado/real, correlation ID, mensagem e detalhes.
- `app/observability/service.py` centraliza emissao de eventos, resumo operacional e readiness
  por componente.
- Endpoints privados adicionados:
  - `GET /api/v1/observability/projects/{project_id}/events`
  - `GET /api/v1/observability/projects/{project_id}/summary`
  - `GET /api/v1/observability/readiness`
- Providers OpenRouter e provider de fala enviam `X-Correlation-ID` quando houver contexto de
  requisicao.
- `redact_secrets` e `redact_mapping` removem chaves, tokens e segredos de erros/detalhes antes
  de persistir ou relatar.
- Readiness separa API, banco, Redis, broker do worker, FFmpeg, OpenRouter e speech provider.

## Pendencias

- Padronizar logs estruturados diretamente em todos os providers, alem dos eventos persistidos.
- Expandir eventos de job para todos os estados do ciclo (`queued`, `progress`, `cancelled`) e
  para todos os tipos de job, nao apenas video/finalizacao.

## Entregaveis

- Eventos operacionais por projeto.
- Logs estruturados nos caminhos principais.
- Dashboard de diagnostico.
- Politica de redacao de segredos em erros.

## Criterios de aceite

- Uma falha de provider pode ser rastreada por correlation ID.
- Usuario recebe mensagem amigavel e operador ve detalhe tecnico seguro.
- Health/readiness diferencia API, banco, Redis, worker e dependencias externas.
