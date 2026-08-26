# Roadmap de migração: Storytelling → Meta + Vibes

Este diretório descreve a migração do projeto `jonata1200/storytelling` para uma arquitetura em que:

- **Meta** é o provedor de raciocínio/texto e da biblioteca visual.
- **Vibes** é o provedor de geração de vídeo.
- **Ollama Cloud e OpenRouter são removidos completamente ao final da migração.**
- `Scene` e `Shot` continuam sendo a estrutura narrativa central.
- `Asset`, `Artifact`, `GenerationJob`, custos, observabilidade e versionamento existentes são preservados.
- A integração com serviços externos continua desacoplada do domínio por contratos de provider.

## Princípio de migração

Não apagar Ollama/OpenRouter no início. Primeiro criar e validar os substitutos. A remoção física acontece apenas na Fase 07, depois que Meta + Vibes estiverem cobertos por testes e pelo fluxo de ponta a ponta.

Isso mantém a branch executável durante a migração e reduz o risco de uma refatoração "big bang".

## Fases

1. [Fase 00 — Descoberta técnica e decisões de integração](./00-fase-descoberta-e-decisoes.md)
2. [Fase 01 — Arquitetura de providers e neutralização do domínio](./01-fase-arquitetura-providers.md)
3. [Fase 02 — Meta para texto, roteiro e agentes](./02-fase-meta-texto.md)
4. [Fase 03 — Meta para biblioteca visual e imagens](./03-fase-meta-biblia-visual.md)
5. [Fase 04 — Vibes para geração de vídeo](./04-fase-vibes-video.md)
6. [Fase 05 — Pipeline centrado em Shot e continuidade](./05-fase-shot-pipeline.md)
7. [Fase 06 — Workers, QA, resiliência e interface](./06-fase-workers-qa-resiliencia.md)
8. [Fase 07 — Cutover e remoção total de Ollama/OpenRouter](./07-fase-cutover-remocao-legado.md)

## Ordem obrigatória

`00 → 01 → 02 → 03 → 04 → 05 → 06 → 07`

As fases 02 e 03 podem ter desenvolvimento parcialmente paralelo depois que a Fase 01 estiver concluída. A Fase 07 não deve começar antes de todos os critérios de aceite das Fases 02–06 estarem verdes.

## Estado atual relevante do repositório

O projeto já possui uma base apropriada para a migração:

- FastAPI + NiceGUI.
- SQLAlchemy async + PostgreSQL/pgvector.
- Redis.
- `StoryIdea`, `Script`, `Scene` e `Shot`.
- `Character`, `Location` e `VisualReference`.
- `Asset` e versionamento de assets.
- `GenerationJob` com status, tentativas, idempotência e custos.
- protocolo `VideoProvider` com `submit`, `poll` e `download`.
- geração contínua e extração do frame final via FFmpeg.
- custos e observabilidade.
- testes com marcadores específicos para providers, integração, UI, smoke e segurança.

A migração deve evoluir essa base; não reescrevê-la.

## Resultado final esperado

```text
Ideia / Briefing
       ↓
Meta Text
       ↓
StoryIdea → Script → Scene → Shot
                          ↓
                ShotGenerationSpec
                 ↙              ↘
        Meta Visual Bible     Prompt Compiler
                 ↓                 ↓
       VisualReference          Vibes
                 ↘                 ↓
                    Video Asset
                         ↓
                    QA / Review
                         ↓
                  Final Frame
                         ↓
                    próximo Shot
```

## Regra arquitetural final

Nenhum módulo de domínio deve importar diretamente `Meta...Provider` ou `Vibes...Provider`.

O domínio deve trabalhar somente com contratos/factories:

```text
LLMProvider
ImageProvider
VideoProvider
ProviderRegistry / Factory
```

Assim, detalhes de API, browser automation, autenticação e polling ficam confinados à camada de providers/workers.
