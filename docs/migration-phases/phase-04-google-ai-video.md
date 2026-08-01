# Fase 04 - Videos com Google AI

## Objetivo

Migrar geracao de video para Google AI / Gemini API usando Gemini Omni Flash e/ou
Veo.

## Resultado Esperado

`VIDEO_PROVIDER=google_ai` deve gerar clipes a partir de texto e, principalmente,
a partir dos keyframes/imagens gerados na fase anterior.

## Base Tecnica

As docs oficiais do Google AI dizem que a Gemini API oferece dois caminhos para
geracao de video:

- Gemini Omni Flash: recomendado como padrao para video, coerencia e edicao conversacional.
- Veo 3.1: indicado para controles especificos, extensao de cena, controle de frame final e fluxos legados.

O guia do Veo descreve geracao assincrona, com operacao de longa duracao e
polling ate o video ficar pronto.

## Variaveis Propostas

```env
VIDEO_PROVIDER=google_ai
GOOGLE_AI_VIDEO_MODEL=veo-3.1-generate-preview
GOOGLE_AI_VIDEO_FAST_MODEL=veo-3.1-fast-generate-preview
GOOGLE_AI_VIDEO_DEFAULT_DURATION_SECONDS=8
GOOGLE_AI_VIDEO_POLL_INTERVAL_SECONDS=10
GOOGLE_AI_VIDEO_POLL_TIMEOUT_SECONDS=900
```

## Checklist

- [ ] Adicionar `google_ai` como provider de video suportado.
- [ ] Adicionar settings de modelo, duracao, polling e timeout.
- [ ] Criar `app/providers/video/google_ai.py`.
- [ ] Implementar `generate_from_text`.
- [ ] Implementar `generate_from_image`.
- [ ] Implementar suporte a imagem inicial quando houver storyboard/keyframe.
- [ ] Implementar suporte a imagens de referencia quando o modelo permitir.
- [ ] Mapear `aspect_ratio` para `9:16` ou `16:9`.
- [ ] Mapear `duration_seconds` para duracoes aceitas pelo modelo.
- [ ] Mapear resolucao para `720p`, `1080p` ou `4k` quando aplicavel.
- [ ] Implementar polling de operacao longa.
- [ ] Baixar video final para storage local.
- [ ] Persistir `external_job_id`, `provider`, `model`, prompt e metadados.
- [ ] Atualizar `_video_provider_for_project`.
- [ ] Atualizar estimativa de custo para video.
- [ ] Adicionar testes unitarios para submit, polling, download e erro.
- [ ] Adicionar smoke test real atras de flag explicita.

## Decisoes de Modelo

- [ ] Definir se o default sera Gemini Omni Flash ou Veo.
- [ ] Definir quando usar modelo rapido.
- [ ] Definir quando gerar video com audio nativo.
- [ ] Definir se audio nativo sera descartado quando houver dublagem posterior.

## Criterios de Aceite

- Um frame de storyboard aprovado gera um clipe real com `google_ai`.
- Jobs longos mostram status rastreavel.
- Timeout e falhas transientes sao tratados sem travar a pipeline.
- O video final e salvo como asset e ligado ao storyboard frame.
