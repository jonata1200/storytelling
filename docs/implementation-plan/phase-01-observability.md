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

- [ ] Criar uma consulta de ultimas execucoes de prompt por projeto usando `PromptExecution`.
- [ ] Expor duracao, provider, modelo, tarefa, custo estimado, data e status da execucao.
- [ ] Adicionar resumo por tarefa: quantidade, media, minimo, maximo e ultima execucao.
- [ ] Incluir jobs recentes no mesmo painel: status, progresso, tentativas, erro e payload resumido.
- [ ] Emitir eventos operacionais para etapas narrativas, nao apenas video.
- [ ] Registrar inicio, sucesso e falha de `ideas`, `script`, `scenes`, `visual`, `storyboard`, `finalization` e `quality`.
- [ ] Redigir erros antes de exibir ou gravar detalhes sensiveis.
- [ ] Adicionar componente visual na UI do projeto com "Execucoes IA".
- [ ] Adicionar endpoint API para summary operacional por projeto, se a UI nao puder reutilizar os endpoints atuais.
- [ ] Melhorar readiness para diferenciar Redis principal, broker Celery e backend de resultado.
- [ ] Adicionar status de worker ativo, nao apenas broker respondendo.
- [ ] Mostrar a URL base do provider sem chave/sigilo.
- [ ] Adicionar testes unitarios para agregacao de metricas.
- [ ] Adicionar testes de UI/helper para renderizacao dos estados vazio, sucesso e falha.

## Criterios de Aceite

- [ ] O usuario consegue ver qual etapa esta demorando e ha quanto tempo.
- [ ] Falhas de provider aparecem com mensagem redigida e tarefa associada.
- [ ] Readiness acusa worker/broker indisponivel de forma compreensivel.
- [ ] Testes, lint e mypy passam.

## Validacao Recomendada

- [ ] `ruff check .`
- [ ] `mypy app tests`
- [ ] `python -m pytest tests/test_observability_events.py tests/test_jobs.py -q`
- [ ] `python -m pytest -q`
