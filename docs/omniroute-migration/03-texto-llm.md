# Fase 3 - Migração de texto e JSON estruturado

Objetivo: migrar geração de ideias, roteiro, cenas/planos e agente diretor para
OmniRoute usando endpoint compatível com OpenAI Chat Completions.

## Checklist

- [x] Criar `app/providers/llm/omniroute.py`.
- [x] Implementar provider com `provider_name = "omniroute"`.
- [x] Usar `POST {OMNIROUTE_BASE_URL}/chat/completions`.
- [x] Enviar `Authorization: Bearer <OMNIROUTE_API_KEY>`.
- [x] Enviar `Content-Type: application/json`.
- [x] Manter `response_format={"type":"json_object"}` quando suportado.
- [x] Implementar fallback sem `response_format` para erros 400/422, se
      necessário.
- [x] Reaproveitar parser de `choices[0].message.content`.
- [x] Redigir erros com `redact_secrets`.
- [x] Propagar `X-Correlation-ID`.
- [x] Atualizar `llm_provider_for_task` para escolher OmniRoute.
- [x] Atualizar preferências/modelos por etapa para permitir provider
      `omniroute`.
- [x] Criar testes unitários de request, headers, fallback e parsing.
- [x] Criar teste de erro quando `OMNIROUTE_API_KEY` está ausente.

## Fluxos Impactados

- Ideias iniciais.
- Story Bible.
- Roteiro.
- Cenas e planos.
- Revisão de roteiro.
- Agente diretor.

## Critérios De Aceite

- [x] Todos os fluxos de texto usam o provider OmniRoute quando
      `AI_PROVIDER=omniroute`.
- [x] OpenRouter ainda funciona quando selecionado.
- [x] JSON inválido continua sendo recusado.
- [x] `ruff`, `mypy` e testes de geração passam.

## Resultado

- Provider `OmniRouteLLMProvider` criado com endpoint OpenAI-compatible.
- Seleção de provider por tarefa agora instancia OmniRoute ou OpenRouter.
- Laboratório de ideias livres respeita `AI_PROVIDER=omniroute`.
- Testes adicionados em `tests/test_omniroute_provider.py`.
