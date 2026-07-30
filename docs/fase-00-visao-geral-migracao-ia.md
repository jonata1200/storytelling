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

## Decisoes Iniciais

- Imagem e video podem ficar temporariamente indisponiveis em ambiente local ou
  staging durante a troca de provider. Antes de producao, a aplicacao deve
  mostrar estado indisponivel claro em vez de falhar silenciosamente.
- Modelos iniciais sugeridos: `llama3.1:8b` para Ollama,
  `llama-3.3-70b-versatile` para Groq e `openai/gpt-oss-20b` para NVIDIA NIM.
- Fallback automatico de texto comeca desligado por padrao. A fase 04 pode
  habilitar fallback opt-in apos testes isolados de cada provider.
- Veo AI Free via cookie/sessao deve ser habilitado apenas como recurso local e
  experimental.
- OmniRoute permanece como provider legado somente enquanto a nova camada ainda
  nao estiver pronta.

## Rollback Por Fase

- Fase 01: reverter apenas documentos e `.gitignore`, sem impacto funcional.
- Fase 02: manter o provider OmniRoute antigo selecionavel ate a camada generica
  estar coberta por testes.
- Fase 03: voltar `TEXT_PROVIDER` para o ultimo provider funcional se algum
  provider novo falhar.
- Fase 04: desligar fallback automatico e manter selecao manual.
- Fase 05 e 06: desligar `VEO_AI_FREE_ENABLED` e ocultar imagem/video
  experimental na UI.
- Fase 07: executar somente quando nao houver dependencia ativa de OmniRoute em
  codigo, testes, README e `.env.example`.

## Checklist

- [x] Confirmar que imagem/video podem ficar indisponiveis temporariamente durante a migracao.
- [x] Confirmar modelos iniciais para Ollama, Groq e NVIDIA NIM.
- [x] Definir se fallback automatico entre providers de texto sera ligado por padrao.
- [x] Definir se Veo AI Free via cookie sera habilitado apenas em ambiente local.
- [x] Garantir que `.runtime/`, cookies e tokens estejam ignorados pelo Git.
- [x] Criar um plano de rollback por fase.

## Criterios De Saida

- [x] Todas as fases possuem arquivo proprio em `docs/`.
- [x] Cada fase possui checklist operacional.
- [x] Riscos de integracao via cookie estao documentados.
- [x] A ordem de implementacao esta clara.
