# Fase 2 - Configuração e abstração de providers

Objetivo: permitir que a aplicação escolha OmniRoute sem remover OpenRouter
imediatamente.

## Checklist

- [ ] Adicionar variáveis de ambiente:
      `OMNIROUTE_API_KEY`, `OMNIROUTE_BASE_URL`, `OMNIROUTE_DEFAULT_MODEL`,
      `OMNIROUTE_IMAGE_MODEL`, `OMNIROUTE_VIDEO_MODEL`.
- [ ] Avaliar se será necessário `OMNIROUTE_SPEECH_MODEL` ou se o speech usará
      as configurações atuais.
- [ ] Adicionar `AI_PROVIDER=omniroute|openrouter` ou campos específicos por
      mídia, como `TEXT_PROVIDER`, `IMAGE_PROVIDER`, `VIDEO_PROVIDER`.
- [ ] Criar política de validação de modelos genérica, sem nomes presos a
      OpenRouter.
- [ ] Manter bloqueio de modelos `mock-*`.
- [ ] Manter bloqueio de modelos gratuitos se a política de produção continuar
      exigindo modelos pagos/estáveis.
- [ ] Atualizar `.env.example`.
- [ ] Atualizar README com as novas variáveis.
- [ ] Ajustar UI de modelos para não mencionar apenas OpenRouter.
- [ ] Criar testes unitários para leitura das novas configurações.

## Ações técnicas sugeridas

- [ ] Criar `app/config/provider_policy.py`.
- [ ] Migrar `validate_openrouter_model_name` para um validador genérico.
- [ ] Manter aliases temporários para não quebrar testes existentes.
- [ ] Adicionar `normalize_omniroute_api_key`, se a OmniRoute tiver prefixo
      obrigatório.
- [ ] Evitar renomear tabelas ou colunas neste momento.

## Critérios de aceite

- [ ] A aplicação inicia com OpenRouter como provider padrão.
- [ ] A aplicação aceita configuração OmniRoute sem quebrar importações.
- [ ] Testes de settings e políticas de modelo passam.
- [ ] Não há chamada real para OmniRoute ainda.

