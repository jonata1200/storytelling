# Fase 3 - Migração de texto e JSON estruturado

Objetivo: migrar geração de ideias, roteiro, cenas/planos e agente diretor para
OmniRoute usando endpoint compatível com OpenAI Chat Completions.

## Checklist

- [ ] Criar `app/providers/llm/omniroute.py`.
- [ ] Implementar provider com `provider_name = "omniroute"`.
- [ ] Usar `POST {OMNIROUTE_BASE_URL}/chat/completions`.
- [ ] Enviar `Authorization: Bearer <OMNIROUTE_API_KEY>`.
- [ ] Enviar `Content-Type: application/json`.
- [ ] Manter `response_format={"type":"json_object"}` quando suportado.
- [ ] Implementar fallback sem `response_format` para erros 400/422, se
      necessário.
- [ ] Reaproveitar parser de `choices[0].message.content`.
- [ ] Redigir erros com `redact_secrets`.
- [ ] Propagar `X-Correlation-ID`.
- [ ] Atualizar `llm_provider_for_task` para escolher OmniRoute.
- [ ] Atualizar preferências/modelos por etapa para permitir provider
      `omniroute`.
- [ ] Criar testes unitários de request, headers, fallback e parsing.
- [ ] Criar teste de erro quando `OMNIROUTE_API_KEY` está ausente.

## Fluxos impactados

- Ideias iniciais.
- Story Bible.
- Roteiro.
- Cenas e planos.
- Revisão de roteiro.
- Agente diretor.

## Critérios de aceite

- [ ] Todos os fluxos de texto funcionam com `AI_PROVIDER=omniroute`.
- [ ] OpenRouter ainda funciona quando selecionado.
- [ ] JSON inválido continua sendo recusado.
- [ ] `ruff`, `mypy` e testes de geração passam.

