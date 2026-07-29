# Fase 01 - Observabilidade Operacional

## Objetivo

Dar visibilidade clara sobre tempo, custo, modelo, provider, tentativas e erro de
cada etapa de IA/job. A meta e reduzir a sensacao de "travou" e facilitar
diagnostico sem depender de logs locais.

## Escopo

- Painel de execucoes por projeto.
- Eventos operacionais mais granulares.
- Metricas agregadas por tarefa.
- Readiness mais util para banco, Redis, worker e providers.

## Checklist de Implementacao

- [x] Criar uma consulta de ultimas execucoes de prompt por projeto usando `PromptExecution`.
- [x] Expor duracao, provider, modelo, tarefa, custo estimado, data e status da execucao.
- [x] Adicionar resumo por tarefa: quantidade, media, minimo, maximo e ultima execucao.
- [x] Incluir jobs recentes no mesmo painel: status, progresso, tentativas, erro e payload resumido.
- [x] Emitir eventos operacionais para etapas narrativas, nao apenas video.
- [x] Registrar inicio, sucesso e falha de `ideas`, `script`, `scenes`, `visual`, `storyboard`, `finalization` e `quality`.
- [x] Redigir erros antes de exibir ou gravar detalhes sensiveis.
- [x] Adicionar componente visual na UI do projeto com "Execucoes IA".
- [x] Adicionar endpoint API para summary operacional por projeto, se a UI nao puder reutilizar os endpoints atuais.
- [x] Melhorar readiness para diferenciar Redis principal, broker Celery e backend de resultado.
- [x] Adicionar status de worker ativo, nao apenas broker respondendo.
- [x] Mostrar a URL base do provider sem chave/sigilo.
- [x] Adicionar testes unitarios para agregacao de metricas.
- [x] Adicionar testes de UI/helper para renderizacao dos estados vazio, sucesso e falha.

## Criterios de Aceite

- [x] O usuario consegue ver qual etapa esta demorando e ha quanto tempo.
- [x] Falhas de provider aparecem com mensagem redigida e tarefa associada.
- [x] Readiness acusa worker/broker indisponivel de forma compreensivel.
- [x] Testes, lint e mypy passam.

## Validacao Recomendada

- [x] `ruff check .`
- [x] `mypy app tests`
- [x] `python -m pytest tests/test_observability_events.py tests/test_jobs.py -q`
- [x] `python -m pytest -q`
