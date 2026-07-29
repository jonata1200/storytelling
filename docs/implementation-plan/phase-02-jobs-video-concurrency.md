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

- [ ] Adicionar configuracao `video_generation_concurrency` em settings/preferencias.
- [ ] Validar limites minimo e maximo para concorrencia.
- [ ] Refatorar `generate_video_clips` para preparar jobs antes de executar provider.
- [ ] Preservar idempotency key por frame, variante, provider, modelo e prompt.
- [ ] Executar geracoes de clipe com concorrencia limitada.
- [ ] Manter budget check antes da submissao dos clipes.
- [ ] Atualizar progresso do job por frame concluido/falho.
- [ ] Separar provider de video em metodos conceituais: submit, poll, download.
- [ ] Persistir `external_job_id` logo apos submissao.
- [ ] Permitir retomada de polling quando job ja tem `external_job_id`.
- [ ] Evitar polling bloqueante prolongado dentro de uma unica chamada.
- [ ] Definir timeout configuravel para submissao, polling total e download.
- [ ] Adicionar retry especifico para falhas transientes de provider.
- [ ] Garantir que falha de um clipe nao interrompa todos os demais clipes.
- [ ] Emitir eventos por clipe iniciado, concluido e falho.
- [ ] Adicionar testes para concorrencia limitada.
- [ ] Adicionar testes para retomada de job com `external_job_id`.
- [ ] Adicionar testes para idempotencia e budget check.

## Criterios de Aceite

- [ ] Gerar varios clipes usa concorrencia limitada configuravel.
- [ ] A UI mostra progresso incremental em vez de uma espera unica.
- [ ] Jobs interrompidos podem ser retomados sem duplicar clipes.
- [ ] Falhas parciais ficam isoladas por frame.
- [ ] Testes, lint e mypy passam.

## Validacao Recomendada

- [ ] `python -m pytest tests/test_video_retry.py tests/test_video_durations.py -q`
- [ ] `python -m pytest tests/test_omniroute_video_speech.py -q`
- [ ] `ruff check .`
- [ ] `mypy app tests`
- [ ] `python -m pytest -q`
