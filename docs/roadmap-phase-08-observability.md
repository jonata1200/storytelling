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

- [ ] Mapear pontos principais de falha por etapa.
- [ ] Padronizar logs estruturados nos services.
- [ ] Padronizar logs estruturados nos providers.
- [ ] Propagar correlation ID em chamadas internas relevantes.
- [ ] Criar modelo de evento operacional por projeto.
- [ ] Persistir eventos de job: queued, started, progress, succeeded, failed e cancelled.
- [ ] Registrar modelo/provider usado em cada evento de IA.
- [ ] Registrar custo estimado e real nos eventos relevantes.
- [ ] Redigir segredos em logs e mensagens de erro.
- [ ] Criar resumo operacional por projeto.
- [ ] Criar dashboard de readiness.
- [ ] Separar readiness de API, banco, Redis, worker, FFmpeg e OpenRouter.
- [ ] Adicionar testes de redacao de segredos.
- [ ] Adicionar testes de emissao de eventos.

## Entregaveis

- Eventos operacionais por projeto.
- Logs estruturados nos caminhos principais.
- Dashboard de diagnostico.
- Politica de redacao de segredos em erros.

## Criterios de aceite

- Uma falha de provider pode ser rastreada por correlation ID.
- Usuario recebe mensagem amigavel e operador ve detalhe tecnico seguro.
- Health/readiness diferencia API, banco, Redis, worker e dependencias externas.
