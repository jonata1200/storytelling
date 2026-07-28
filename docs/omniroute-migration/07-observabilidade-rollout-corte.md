# Fase 7 - Observabilidade, rollout e corte final

Objetivo: acompanhar a migração em produção, manter fallback temporário e remover
OpenRouter somente quando OmniRoute estiver validado.

## Checklist

- [ ] Adicionar componentes de readiness para OmniRoute:
      texto, imagem, vídeo e speech, se aplicável.
- [ ] Registrar provider e modelo nos eventos operacionais.
- [ ] Registrar provider e modelo nos custos estimados.
- [ ] Criar logs claros para erros OmniRoute.
- [ ] Validar redaction de `OMNIROUTE_API_KEY`.
- [ ] Executar fluxo completo em ambiente local:
      ideia, roteiro, cenas, visual, storyboard, vídeo, finalização e QA.
- [ ] Executar fluxo completo em ambiente de staging.
- [ ] Comparar qualidade de saída com OpenRouter.
- [ ] Definir janela de rollback.
- [ ] Manter OpenRouter como fallback até todos os smoke tests passarem.
- [ ] Trocar provider padrão para OmniRoute.
- [ ] Atualizar README e `.env.example`.
- [ ] Atualizar textos da UI que mencionam OpenRouter.
- [ ] Remover configurações OpenRouter somente em uma tarefa futura e separada.

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

- [ ] OmniRoute é o provider padrão.
- [ ] OpenRouter não é necessário no fluxo principal.
- [ ] O usuário recebe mensagens claras em falhas de provider.
- [ ] O rollback para OpenRouter ainda é possível.
- [ ] `ruff`, `mypy` e `pytest` passam.

