# Fase 2 - Configuração e abstração de providers

Objetivo: permitir que a aplicação escolha OmniRoute sem remover OpenRouter
imediatamente.

## Checklist

- [x] Adicionar variáveis de ambiente:
      `OMNIROUTE_API_KEY`, `OMNIROUTE_BASE_URL`, `OMNIROUTE_DEFAULT_MODEL`,
      `OMNIROUTE_IMAGE_MODEL`, `OMNIROUTE_VIDEO_MODEL`.
- [x] Avaliar se será necessário `OMNIROUTE_SPEECH_MODEL` ou se o speech usará
      as configurações atuais.
- [x] Adicionar `AI_PROVIDER=omniroute|openrouter` ou campos específicos por
      mídia, como `TEXT_PROVIDER`, `IMAGE_PROVIDER`, `VIDEO_PROVIDER`.
- [x] Criar política de validação de modelos genérica, sem nomes presos a
      OpenRouter.
- [x] Manter bloqueio de modelos `mock-*`.
- [x] Manter bloqueio de modelos gratuitos se a política de produção continuar
      exigindo modelos pagos/estáveis.
- [x] Atualizar `.env.example`.
- [x] Atualizar README com as novas variáveis.
- [x] Ajustar UI de modelos para não mencionar apenas OpenRouter.
- [x] Criar testes unitários para leitura das novas configurações.

## Ações Técnicas Sugeridas

- [x] Criar `app/config/provider_policy.py`.
- [x] Migrar `validate_openrouter_model_name` para um validador genérico.
- [x] Manter aliases temporários para não quebrar testes existentes.
- [x] Adicionar `normalize_omniroute_api_key`, se a OmniRoute tiver prefixo
      obrigatório.
- [x] Evitar renomear tabelas ou colunas neste momento.

## Critérios De Aceite

- [x] A aplicação inicia com OpenRouter como provider padrão.
- [x] A aplicação aceita configuração OmniRoute sem quebrar importações.
- [x] Testes de settings e políticas de modelo passam.
- [x] Não há chamada real para OmniRoute ainda.

## Resultado

- Variáveis `OMNIROUTE_*`, `AI_PROVIDER`, `TEXT_PROVIDER`, `IMAGE_PROVIDER` e
  `VIDEO_PROVIDER` adicionadas em settings e `.env.example`.
- Política genérica criada em `app/config/provider_policy.py`.
- Aliases antigos de `app/config/model_policy.py` preservados para compatibilidade.
- OpenRouter segue como provider real padrão.
- OmniRoute já pode ser configurado e salvo, mas chamadas reais ficam bloqueadas
  até as fases específicas de texto, imagem e vídeo.
- Testes de settings, preferências e política genérica adicionados.
