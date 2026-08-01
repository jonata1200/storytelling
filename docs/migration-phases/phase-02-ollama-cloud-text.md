# Fase 02 - Texto com Ollama Cloud

## Objetivo

Usar Ollama Cloud como provider principal para tudo que envolve texto na
aplicacao.

## Resultado Esperado

Todas as tarefas narrativas e operacionais de texto devem passar por
`TEXT_PROVIDER=ollama_cloud`, com fallback temporario para `nvidia_nim`.

## Variaveis Propostas

```env
TEXT_PROVIDER=ollama_cloud
TEXT_PROVIDER_FALLBACKS=nvidia_nim
OLLAMA_CLOUD_BASE_URL=https://ollama.com/api
OLLAMA_CLOUD_API_KEY=...
OLLAMA_CLOUD_DEFAULT_MODEL=...
```

## Checklist

- [x] Adicionar `ollama_cloud` em `SUPPORTED_TEXT_PROVIDERS`.
- [x] Adicionar campos `ollama_cloud_api_key`, `ollama_cloud_base_url` e `ollama_cloud_default_model` em settings.
- [x] Criar `app/providers/llm/ollama_cloud.py`.
- [x] Implementar chamada ao contrato nativo do Ollama API.
- [x] Adaptar respostas para `LLMResult`.
- [x] Garantir JSON valido nas tarefas estruturadas.
- [x] Adicionar mensagens de erro claras para chave ausente, modelo ausente e resposta invalida.
- [x] Atualizar `llm_provider_for_name`.
- [x] Atualizar `provider_display_name`, `provider_api_key`, `provider_model` e readiness.
- [x] Atualizar tela de configuracoes para aceitar Ollama Cloud.
- [x] Criar testes unitarios com mocks de HTTP.
- [x] Criar smoke test real atras de flag explicita.

## Tarefas Cobertas

- [x] Ideias narrativas.
- [x] Briefing expandido.
- [x] Roteiro.
- [x] Cenas e planos.
- [x] Perfis textuais da biblioteca visual.
- [x] Prompts de imagem.
- [x] Prompts de storyboard.
- [x] Prompts de video.
- [x] Legendas, textos auxiliares e traducoes.

## Criterios de Aceite

- `TEXT_PROVIDER=ollama_cloud` gera roteiro completo.
- As tarefas estruturadas retornam JSON parseavel.
- Falha no Ollama Cloud aciona fallback quando configurado.
- Testes automatizados nao fazem chamadas reais por padrao.

## Status de Validacao

- Testes unitarios com HTTP mockado implementados e executados.
- Smoke test real permanece opcional via `STORYTELLING_TEXT_PROVIDER_SMOKE=1`.
