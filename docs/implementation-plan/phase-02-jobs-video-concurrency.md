# Fase 02 - Jobs, Video e Concorrencia

## Objetivo

Reduzir o tempo percebido nas etapas mais caras, principalmente video, sem
perder controle de custo, idempotencia, retry e retomada.

## Escopo

- Concorrencia limitada para clipes de video.
- Separacao entre submissao, polling e download.
- Melhor progresso em jobs longos.
- Configuracao de limites por etapa.

## Checklist de Implementacao

- [x] Adicionar configuracao `video_generation_concurrency` em settings/preferencias.
- [x] Validar limites minimo e maximo para concorrencia.
- [x] Refatorar `generate_video_clips` para preparar jobs antes de executar provider.
- [x] Preservar idempotency key por frame, variante, provider, modelo e prompt.
- [x] Executar geracoes de clipe com concorrencia limitada.
- [x] Manter budget check antes da submissao dos clipes.
- [x] Atualizar progresso do job por frame concluido/falho.
- [x] Separar provider de video em metodos conceituais: submit, poll, download.
- [x] Persistir `external_job_id` logo apos submissao.
- [x] Permitir retomada de polling quando job ja tem `external_job_id`.
- [x] Evitar polling bloqueante prolongado dentro de uma unica chamada.
- [x] Definir timeout configuravel para submissao, polling total e download.
- [x] Adicionar retry especifico para falhas transientes de provider.
- [x] Garantir que falha de um clipe nao interrompa todos os demais clipes.
- [x] Emitir eventos por clipe iniciado, concluido e falho.
- [x] Adicionar testes para concorrencia limitada.
- [x] Adicionar testes para retomada de job com `external_job_id`.
- [x] Adicionar testes para idempotencia e budget check.

## Criterios de Aceite

- [x] Gerar varios clipes usa concorrencia limitada configuravel.
- [x] A UI mostra progresso incremental em vez de uma espera unica.
- [x] Jobs interrompidos podem ser retomados sem duplicar clipes.
- [x] Falhas parciais ficam isoladas por frame.
- [x] Testes, lint e mypy passam.

## Validacao Recomendada

- [x] `python -m pytest tests/test_video_retry.py tests/test_video_durations.py -q`
- [x] `python -m pytest tests/test_omniroute_video_speech.py -q`
- [x] `ruff check .`
- [x] `mypy app tests`
- [x] `python -m pytest -q`
