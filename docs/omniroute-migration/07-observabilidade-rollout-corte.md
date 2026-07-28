# Fase 7 - Observabilidade, rollout e corte final

Status: corte aplicado em configuração e código. OmniRoute é o provider padrão
para texto, imagem e vídeo; OpenRouter permanece disponível como rollback
temporário por configuração.

Objetivo: acompanhar a migração em produção, manter fallback temporário e remover
OpenRouter somente quando OmniRoute estiver validado em ambiente real.

## Checklist

- [x] Adicionar componentes de readiness para OmniRoute:
      texto, imagem, vídeo e speech, se aplicável.
- [x] Registrar provider e modelo nos eventos operacionais.
- [x] Registrar provider e modelo nos custos estimados.
- [x] Criar logs claros para erros OmniRoute.
- [x] Validar redaction de `OMNIROUTE_API_KEY` e tokens Bearer.
- [ ] Executar fluxo completo em ambiente local:
      ideia, roteiro, cenas, visual, storyboard, vídeo, finalização e QA.
- [ ] Executar fluxo completo em ambiente de staging.
- [ ] Comparar qualidade de saída com OpenRouter.
- [x] Definir janela de rollback.
- [x] Manter OpenRouter como fallback até todos os smoke tests reais passarem.
- [x] Trocar provider padrão para OmniRoute.
- [x] Atualizar README e `.env.example`.
- [x] Atualizar textos da UI que mencionam OpenRouter como provider principal.
- [x] Remover configurações OpenRouter somente em uma tarefa futura e separada.

## Implementação

- Default global alterado para `AI_PROVIDER=omniroute`.
- `DEFAULT_PROVIDER` agora aponta para `omniroute`.
- Readiness agora separa:
  `text_provider`, `image_provider`, `video_provider` e `character_speech`.
- Cada componente de readiness mostra provider, modelo, base URL e se há chave
  configurada, sem expor segredo.
- Eventos operacionais agora registram provider, modelo, operação e custos também
  no log estruturado.
- Speech por personagem agora emite evento `speech_generation` com provider,
  modelo, custo estimado, speaker e `voice_profile_id`.
- Redaction cobre `OMNIROUTE_API_KEY=...` e `Authorization: Bearer ...`.
- Erros de rede, timeout e JSON inválido do provider de vídeo OmniRoute foram
  normalizados com mensagens explícitas.

## Rollback

Janela recomendada: manter rollback disponível por pelo menos uma rodada completa
de validação em staging e uma rodada de produção assistida.

Para rollback global:

```env
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=...
```

Para rollback parcial:

```env
TEXT_PROVIDER=openrouter
IMAGE_PROVIDER=openrouter
VIDEO_PROVIDER=openrouter
OPENROUTER_API_KEY=...
```

Speech continua independente:

```env
SPEECH_PROVIDER=openai_compatible
SPEECH_API_KEY=...
SPEECH_MODEL=...
```

OpenRouter não deve ser removido nesta fase. A remoção de variáveis, providers,
testes e documentação deve ser uma tarefa futura separada, após smoke real e
comparação de qualidade.

## Smoke test final

- [ ] Criar projeto novo.
- [ ] Gerar ideias.
- [ ] Escolher ideia e gerar roteiro.
- [ ] Gerar cenas e planos.
- [ ] Gerar biblioteca visual.
- [ ] Aprovar referências visuais.
- [ ] Gerar storyboard.
- [ ] Gerar clipes de vídeo.
- [ ] Criar timeline final.
- [ ] Sintetizar vozes por personagem, se configurado.
- [ ] Exportar MP4.
- [ ] Rodar QA.
- [ ] Verificar eventos operacionais e custos.

## Critérios de aceite

- [x] OmniRoute é o provider padrão.
- [x] OpenRouter não é necessário no fluxo principal configurado.
- [x] O usuário recebe mensagens claras em falhas de provider.
- [x] O rollback para OpenRouter ainda é possível.
- [x] `ruff`, `mypy` e `pytest` passam.
- [ ] Smoke real completo validado em local/staging.
