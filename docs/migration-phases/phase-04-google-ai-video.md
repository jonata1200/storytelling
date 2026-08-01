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

- [x] Adicionar `google_ai` como provider de video suportado.
- [x] Adicionar settings de modelo, duracao, polling e timeout.
- [x] Criar `app/providers/video/google_ai.py`.
- [x] Implementar `generate_from_text`.
- [x] Implementar `generate_from_image`.
- [x] Implementar suporte a imagem inicial quando houver storyboard/keyframe.
- [x] Implementar suporte a imagens de referencia quando o modelo permitir.
- [x] Mapear `aspect_ratio` para `9:16` ou `16:9`.
- [x] Mapear `duration_seconds` para duracoes aceitas pelo modelo.
- [x] Mapear resolucao para `720p`, `1080p` ou `4k` quando aplicavel.
- [x] Implementar polling de operacao longa.
- [x] Baixar video final para storage local.
- [x] Persistir `external_job_id`, `provider`, `model`, prompt e metadados.
- [x] Atualizar `_video_provider_for_project`.
- [x] Atualizar estimativa de custo para video.
- [x] Adicionar testes unitarios para submit, polling, download e erro.
- [x] Adicionar smoke test real atras de flag explicita.

## Decisoes de Modelo

- [x] Definir se o default sera Gemini Omni Flash ou Veo.
- [x] Definir quando usar modelo rapido.
- [x] Definir quando gerar video com audio nativo.
- [x] Definir se audio nativo sera descartado quando houver dublagem posterior.

## Decisoes Tomadas

- Default inicial: `veo-3.1-generate-preview`, pois a fase prioriza keyframes/storyboard para video.
- Modelo rapido: usar `GOOGLE_AI_VIDEO_FAST_MODEL` quando o operador optar por menor custo/latencia.
- Audio nativo: mantido no arquivo retornado pelo Veo e registrado em metadados como `native_audio=true`.
- Dublagem posterior: a etapa final pode substituir ou descartar o audio nativo sem alterar o provider de video.

## Status de Implementacao

- Provider REST criado em `app/providers/video/google_ai.py` usando `POST /models/{model}:predictLongRunning`.
- Polling implementado via nome de operacao retornado pela API.
- Resultado final aceita video inline base64 ou `uri` para download.
- Configuracao exposta em `.env.example`, README, schema da API e tela de Configuracoes de IA.
- Custos estimados adicionados para `google_ai` com overrides por modelo Veo.
- Testes unitarios cobrem submit, polling, download por URI, video inline e persistencia.
- Smoke real disponivel com `RUN_GOOGLE_AI_VIDEO_SMOKE=1` e `GOOGLE_AI_API_KEY`.

## Criterios de Aceite

- Um frame de storyboard aprovado gera um clipe real com `google_ai`.
- Jobs longos mostram status rastreavel.
- Timeout e falhas transientes sao tratados sem travar a pipeline.
- O video final e salvo como asset e ligado ao storyboard frame.
