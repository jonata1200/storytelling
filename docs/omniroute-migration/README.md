# Plano de migração para OmniRoute

Este plano organiza a transição gradual dos providers atuais baseados em
OpenRouter para OmniRoute/OmniRouters. A migração deve ser feita em fases para
reduzir risco em texto, imagem, vídeo e vozes de personagens.

## Premissas

- A aplicação deve continuar usando modelos reais; providers `mock` seguem
  bloqueados no fluxo de produção.
- OpenRouter deve permanecer disponível como fallback até a fase final de corte.
- OmniRoute deve ser tratado como provider novo, não apenas como renomeação de
  variáveis.
- Chat/texto deve migrar primeiro, imagem depois, vídeo por último.
- Speech deve ser avaliado separadamente porque a aplicação usa vozes
  consistentes por personagem na finalização.

## Fases

1. [Auditoria e preparação](01-auditoria-e-preparacao.md)
2. [Configuração e abstração de providers](02-configuracao-e-abstracao.md)
3. [Migração de texto e JSON estruturado](03-texto-llm.md)
4. [Migração de geração de imagens](04-imagem.md)
5. [Migração de geração de vídeos](05-video.md)
6. [Migração de speech e vozes por personagem](06-speech-e-vozes.md)
7. [Observabilidade, rollout e corte final](07-observabilidade-rollout-corte.md)

## Referências iniciais

- OmniRoute API Reference: https://github.com/diegosouzapw/OmniRoute/blob/main/docs/API_REFERENCE.md
- OmniRouters API docs: https://docs.omnirouters.com/api/

