# Fase 1 - Auditoria e preparação

Objetivo: mapear todos os pontos que dependem de OpenRouter antes de criar o
provider OmniRoute.

## Checklist

- [x] Listar todos os usos de `openrouter`, `OpenRouter` e `OPENROUTER` no
      código.
- [x] Separar dependências em categorias:
      texto, imagem, vídeo, speech, configuração, UI, custos e testes.
- [x] Confirmar quais endpoints OmniRoute serão usados:
      `/v1/chat/completions`, `/v1/images/generations`, rotas de vídeo e rotas
      de speech.
- [x] Confirmar a URL base final:
      local, por exemplo `http://localhost:20128/v1`, ou SaaS, por exemplo
      `https://omnirouters.com/v1`.
- [x] Confirmar formato de API key e política de validação.
- [x] Confirmar modelos equivalentes para:
      roteiro, cenas/planos, imagem, vídeo e speech.
- [x] Registrar incompatibilidades conhecidas entre OpenRouter e OmniRoute.
- [x] Definir se OpenRouter ficará como fallback temporário durante o rollout.

## Arquivos Revisados

- `app/config/settings.py`
- `app/config/model_policy.py`
- `app/config/preferences.py`
- `app/config/runtime_preferences.py`
- `app/config/provider_policy.py`
- `app/generation/model_settings.py`
- `app/providers/llm/openrouter.py`
- `app/providers/image/openrouter.py`
- `app/providers/video/openrouter.py`
- `app/providers/speech/openai_compatible.py`
- `app/visual_bible/image_generation.py`
- `app/storyboards/workflow.py`
- `app/video_generation/service.py`
- `app/ui/routes/settings_page.py`
- `app/ui/workspace/panels.py`
- `app/observability/service.py`
- `README.md`
- `.env.example`

## Critérios De Aceite

- [x] Existe uma lista completa de dependências OpenRouter.
- [x] Existe uma matriz de equivalência de modelos.
- [x] A decisão de rollout, com ou sem fallback OpenRouter, está registrada.
- [x] Nenhuma alteração funcional foi feita nesta fase além de documentação.

## Resultado

- Auditoria registrada em `docs/omniroute-migration/auditoria-openrouter.md`.
- Dependências categorizadas em texto, imagem, vídeo, speech, configuração, UI,
  custos e testes.
- URL base OmniRoute definida como configurável, com default
  `https://omnirouters.com/v1`.
- OpenRouter definido como fallback temporário durante o rollout.
- As alterações funcionais desta rodada pertencem à Fase 2.
