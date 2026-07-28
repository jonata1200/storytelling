# Fase 1 - Auditoria e preparação

Objetivo: mapear todos os pontos que dependem de OpenRouter antes de criar o
provider OmniRoute.

## Checklist

- [ ] Listar todos os usos de `openrouter`, `OpenRouter` e `OPENROUTER` no
      código.
- [ ] Separar dependências em categorias:
      texto, imagem, vídeo, speech, configuração, UI, custos e testes.
- [ ] Confirmar quais endpoints OmniRoute serão usados:
      `/v1/chat/completions`, `/v1/images/generations`, rotas de vídeo e rotas
      de speech.
- [ ] Confirmar a URL base final:
      local, por exemplo `http://localhost:20128/v1`, ou SaaS, por exemplo
      `https://omnirouters.com/v1`.
- [ ] Confirmar formato de API key e política de validação.
- [ ] Confirmar modelos equivalentes para:
      roteiro, cenas/planos, imagem, vídeo e speech.
- [ ] Registrar incompatibilidades conhecidas entre OpenRouter e OmniRoute.
- [ ] Definir se OpenRouter ficará como fallback temporário durante o rollout.

## Arquivos a revisar

- `app/config/settings.py`
- `app/config/model_policy.py`
- `app/config/preferences.py`
- `app/generation/model_settings.py`
- `app/providers/llm/openrouter.py`
- `app/providers/image/openrouter.py`
- `app/providers/video/openrouter.py`
- `app/providers/speech/openai_compatible.py`
- `app/visual_bible/image_generation.py`
- `app/video_generation/service.py`
- `README.md`
- `.env.example`

## Critérios de aceite

- [ ] Existe uma lista completa de dependências OpenRouter.
- [ ] Existe uma matriz de equivalência de modelos.
- [ ] A decisão de rollout, com ou sem fallback OpenRouter, está registrada.
- [ ] Nenhuma alteração funcional foi feita nesta fase além de documentação.

