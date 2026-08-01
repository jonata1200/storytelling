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

- [ ] Adicionar `ollama_cloud` em `SUPPORTED_TEXT_PROVIDERS`.
- [ ] Adicionar campos `ollama_cloud_api_key`, `ollama_cloud_base_url` e `ollama_cloud_default_model` em settings.
- [ ] Criar `app/providers/llm/ollama_cloud.py`.
- [ ] Implementar chamada ao contrato nativo do Ollama API.
- [ ] Adaptar respostas para `LLMResult`.
- [ ] Garantir JSON valido nas tarefas estruturadas.
- [ ] Adicionar mensagens de erro claras para chave ausente, modelo ausente e resposta invalida.
- [ ] Atualizar `llm_provider_for_name`.
- [ ] Atualizar `provider_display_name`, `provider_api_key`, `provider_model` e readiness.
- [ ] Atualizar tela de configuracoes para aceitar Ollama Cloud.
- [ ] Criar testes unitarios com mocks de HTTP.
- [ ] Criar smoke test real atras de flag explicita.

## Tarefas Cobertas

- [ ] Ideias narrativas.
- [ ] Briefing expandido.
- [ ] Roteiro.
- [ ] Cenas e planos.
- [ ] Perfis textuais da biblioteca visual.
- [ ] Prompts de imagem.
- [ ] Prompts de storyboard.
- [ ] Prompts de video.
- [ ] Legendas, textos auxiliares e traducoes.

## Criterios de Aceite

- `TEXT_PROVIDER=ollama_cloud` gera roteiro completo.
- As tarefas estruturadas retornam JSON parseavel.
- Falha no Ollama Cloud aciona fallback quando configurado.
- Testes automatizados nao fazem chamadas reais por padrao.
