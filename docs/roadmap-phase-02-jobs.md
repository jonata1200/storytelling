# Fase 2 - Jobs Longos e Pipeline Recuperavel

## Objetivo

Mover geracoes demoradas para workers e persistir progresso, retry e estado de retomada.

## Escopo

- Transformar Celery de esqueleto para executor real do pipeline.
- Criar tasks para geracao de ideias, roteiro, cenas, visual bible, storyboard, video e finalizacao.
- Persistir status de jobs em tabelas existentes ou nova tabela operacional.
- Substituir `background_tasks.create` da UI por enfileiramento.
- Expor endpoint de status/progresso por projeto/job.
- Implementar retries controlados e idempotencia por etapa.
- Adicionar cancelamento quando o provider suportar ou, no minimo, cancelamento logico.

## Checklist de acoes

- [x] Mapear todos os usos de `background_tasks.create`.
- [x] Mapear chamadas longas aos providers OpenRouter.
- [x] Definir modelo de job: id, projeto, etapa, status, progresso, tentativa, erro e payload.
- [x] Decidir se a tabela atual de generation jobs cobre todas as etapas ou se uma tabela nova e necessaria.
- [x] Criar task Celery para geracao de ideias.
- [x] Criar task Celery para geracao/revisao de roteiro.
- [x] Criar task Celery para cenas e planos.
- [x] Criar task Celery para visual bible e referencias.
- [x] Criar task Celery para storyboard.
- [x] Criar task Celery para video.
- [x] Criar task Celery para animatic, timeline e exportacao.
- [x] Implementar endpoint de consulta de progresso.
- [x] Adaptar UI para disparar jobs em fila.
- [x] Adaptar UI para consultar status persistido.
- [x] Implementar retry com backoff e limite por etapa.
- [x] Implementar idempotencia para evitar duplicacao em reexecucoes.
- [x] Documentar como iniciar worker Celery junto da API.
- [x] Adicionar testes de enfileiramento e retomada.

## Pendencias conhecidas

- [ ] Implementar cancelamento logico/real de jobs.
- [ ] Ampliar testes unitarios especificos para o runner Celery de cada etapa.
- [ ] Remover helpers legados de background async que ficaram apenas como compatibilidade interna.

## Entregaveis

- Tasks Celery reais para as etapas principais.
- UI consultando progresso persistido.
- Retry com backoff e limite por etapa.
- Jobs de video sem polling longo dentro do processo web.
- Documentacao de como iniciar API, Redis e worker.

## Criterios de aceite

- Reiniciar o servidor web nao perde o estado do trabalho em andamento.
- Um job falho pode ser retomado ou reexecutado sem duplicacao acidental.
- A UI mostra estado consistente: queued, running, succeeded, failed, cancelled.
- Testes cobrem enfileiramento, retry e idempotencia de pelo menos uma etapa longa.
