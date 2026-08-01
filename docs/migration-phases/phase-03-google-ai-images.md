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

- [ ] Adicionar `google_ai` em `SUPPORTED_MEDIA_PROVIDERS`.
- [ ] Adicionar settings `google_ai_api_key`, `google_ai_base_url`, `google_ai_image_model` e `google_ai_image_size`.
- [ ] Criar `app/providers/image/google_ai.py`.
- [ ] Implementar geracao de imagem via Gemini API.
- [ ] Implementar edicao de imagem quando houver imagem de referencia.
- [ ] Mapear `aspect_ratio` da aplicacao para `response_format.aspect_ratio`.
- [ ] Mapear resolucao para `image_size` quando aplicavel.
- [ ] Suportar referencias de personagem, local e objeto.
- [ ] Baixar/decodificar imagem gerada e salvar no storage local.
- [ ] Persistir `provider=google_ai`, modelo, prompt, seed quando houver e metadados.
- [ ] Atualizar `_image_provider_for_project` na biblioteca visual.
- [ ] Atualizar provider de imagem usado pelo storyboard.
- [ ] Atualizar estimativa de custo para imagem.
- [ ] Adicionar testes unitarios sem chamada real.
- [ ] Adicionar smoke test real atras de flag explicita.

## Criterios de Aceite

- Biblioteca visual gera imagens com `google_ai`.
- Storyboard gera frames com `google_ai`.
- Imagens geradas sao persistidas como assets locais.
- Prompt, modelo e metadados ficam rastreaveis.
- Erros de quota, chave e modelo aparecem de forma compreensivel na UI/log.
