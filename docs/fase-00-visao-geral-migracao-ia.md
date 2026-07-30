# Fase 00 - Visao Geral Da Migracao De IA

## Objetivo

Remover o OmniRoute/OmniRouter como dependencia principal da aplicacao e migrar a
arquitetura de IA para:

- Texto: `ollama`, `groq` e `nvidia_nim`, todos via API OpenAI-compatible.
- Imagem/video: integracao experimental com Veo AI Free usando sessao/cookie do navegador.

## Principios Da Migracao

- Remover OmniRoute de forma incremental, mantendo a aplicacao funcional a cada fase.
- Criar uma camada generica para provedores OpenAI-compatible antes de adicionar providers.
- Tratar Veo AI Free via cookie como recurso experimental, isolado e reversivel.
- Nao tentar burlar captcha, Cloudflare, rate limit ou mecanismos anti-automacao.
- Nunca versionar chaves, cookies, tokens ou sessoes.
- Manter testes automatizados sem chamadas reais a provedores externos.

## Fases

- Fase 01: inventario e limpeza de acoplamentos OmniRoute.
- Fase 02: camada generica para texto OpenAI-compatible.
- Fase 03: providers de texto Ollama, Groq e NVIDIA NIM.
- Fase 04: UI, preferencias, fallback e observabilidade de texto.
- Fase 05: conexao experimental com Veo AI Free via cookie/sessao.
- Fase 06: provider experimental de imagem/video Veo AI Free.
- Fase 07: remocao final de OmniRoute, hardening e rollout.

## Checklist

- [ ] Confirmar que imagem/video podem ficar indisponiveis temporariamente durante a migracao.
- [ ] Confirmar modelos iniciais para Ollama, Groq e NVIDIA NIM.
- [ ] Definir se fallback automatico entre providers de texto sera ligado por padrao.
- [ ] Definir se Veo AI Free via cookie sera habilitado apenas em ambiente local.
- [ ] Garantir que `.runtime/`, cookies e tokens estejam ignorados pelo Git.
- [ ] Criar um plano de rollback por fase.

## Criterios De Saida

- [ ] Todas as fases possuem arquivo proprio em `docs/`.
- [ ] Cada fase possui checklist operacional.
- [ ] Riscos de integracao via cookie estao documentados.
- [ ] A ordem de implementacao esta clara.
