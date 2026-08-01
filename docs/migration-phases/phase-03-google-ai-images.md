# Fase 03 - Imagens com Google AI

## Objetivo

Migrar geracao e edicao de imagens para Google AI / Gemini API usando os modelos
Nano Banana.

## Resultado Esperado

`IMAGE_PROVIDER=google_ai` deve gerar imagens reais para biblioteca visual,
storyboard e assets auxiliares.

## Base Tecnica

As docs oficiais do Google AI descrevem Nano Banana como as capacidades nativas
de geracao e edicao de imagem do Gemini. Os modelos atuais incluem:

- `gemini-3.1-flash-lite-image`: rapido e de menor custo.
- `gemini-3.1-flash-image`: modelo geral recomendado para equilibrio entre custo, qualidade e latencia.
- `gemini-3-pro-image`: melhor para producao profissional e instrucoes complexas.
- `gemini-2.5-flash-image`: legado; usar apenas se houver motivo especifico.

Imagen nao deve ser o alvo principal porque esta deprecated e tem desligamento
previsto para 17 de agosto de 2026.

## Variaveis Propostas

```env
IMAGE_PROVIDER=google_ai
GOOGLE_AI_API_KEY=...
GOOGLE_AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
GOOGLE_AI_IMAGE_MODEL=gemini-3.1-flash-image
GOOGLE_AI_IMAGE_SIZE=1K
```

## Checklist

- [x] Adicionar `google_ai` em `SUPPORTED_MEDIA_PROVIDERS`.
- [x] Adicionar settings `google_ai_api_key`, `google_ai_base_url`, `google_ai_image_model` e `google_ai_image_size`.
- [x] Criar `app/providers/image/google_ai.py`.
- [x] Implementar geracao de imagem via Gemini API.
- [x] Implementar edicao de imagem quando houver imagem de referencia.
- [x] Mapear `aspect_ratio` da aplicacao para `response_format.aspect_ratio`.
- [x] Mapear resolucao para `image_size` quando aplicavel.
- [x] Suportar referencias de personagem, local e objeto.
- [x] Baixar/decodificar imagem gerada e salvar no storage local.
- [x] Persistir `provider=google_ai`, modelo, prompt e metadados.
- [x] Atualizar `_image_provider_for_project` na biblioteca visual.
- [x] Atualizar provider de imagem usado pelo storyboard.
- [x] Atualizar estimativa de custo para imagem.
- [x] Adicionar testes unitarios sem chamada real.
- [x] Adicionar smoke test real atras de flag explicita.

## Status de Implementacao

- Provider REST criado em `app/providers/image/google_ai.py` usando `POST /v1beta/interactions`.
- Configuracao exposta em `.env.example`, README e tela de Configuracoes de IA.
- Custos estimados adicionados para `google_ai` com overrides por modelo.
- Testes unitarios cobrem payload, referencia local, decodificacao base64 e persistencia.
- Smoke real disponivel com `RUN_GOOGLE_AI_IMAGE_SMOKE=1` e `GOOGLE_AI_API_KEY`.

## Criterios de Aceite

- Biblioteca visual gera imagens com `google_ai`.
- Storyboard gera frames com `google_ai`.
- Imagens geradas sao persistidas como assets locais.
- Prompt, modelo e metadados ficam rastreaveis.
- Erros de quota, chave e modelo aparecem de forma compreensivel na UI/log.
