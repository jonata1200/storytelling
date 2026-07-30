# Fase 03 - Providers De Texto Ollama, Groq E NVIDIA NIM

## Objetivo

Adicionar tres providers de texto alternaveis:

- `ollama`
- `groq`
- `nvidia_nim`

Todos devem usar a camada OpenAI-compatible criada na fase anterior.

## Configuracao Proposta

```env
TEXT_PROVIDER=groq
TEXT_PROVIDER_FALLBACKS=nvidia_nim,ollama

OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_API_KEY=ollama
OLLAMA_DEFAULT_MODEL=llama3.1:8b

GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_API_KEY=
GROQ_DEFAULT_MODEL=llama-3.3-70b-versatile

NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_NIM_API_KEY=
NVIDIA_NIM_DEFAULT_MODEL=openai/gpt-oss-20b
```

## Checklist Ollama

- [x] Adicionar settings `ollama_base_url`, `ollama_api_key`, `ollama_default_model`.
- [x] Permitir `OLLAMA_API_KEY=ollama` como valor padrao local.
- [x] Criar provider `OllamaLLMProvider`.
- [x] Testar chamada local mockada para `/chat/completions`.
- [x] Documentar necessidade de rodar `ollama serve`.
- [x] Documentar necessidade de baixar o modelo localmente.

## Checklist Groq

- [x] Adicionar settings `groq_base_url`, `groq_api_key`, `groq_default_model`.
- [x] Criar provider `GroqLLMProvider`.
- [x] Validar `GROQ_API_KEY` obrigatoria.
- [x] Definir lista inicial de modelos Groq selecionaveis.
- [x] Testar tratamento de rate limit e quota.

## Checklist NVIDIA NIM

- [x] Adicionar settings `nvidia_nim_base_url`, `nvidia_nim_api_key`, `nvidia_nim_default_model`.
- [x] Criar provider `NvidiaNimLLMProvider`.
- [x] Suportar hosted endpoint `https://integrate.api.nvidia.com/v1`.
- [x] Permitir base URL local para NIM self-hosted.
- [x] Definir lista inicial de modelos NVIDIA selecionaveis.
- [x] Testar provider com resposta mockada.

## Checklist Comum

- [x] Atualizar `SUPPORTED_AI_PROVIDERS`.
- [x] Atualizar `provider_display_name`.
- [x] Atualizar `provider_api_key`.
- [x] Atualizar `provider_model`.
- [x] Atualizar `provider_base_url`.
- [x] Atualizar readiness para texto.
- [x] Atualizar testes de settings e provider policy.

## Criterios De Saida

- [x] A aplicacao consegue selecionar qualquer um dos tres providers para texto.
- [x] Testes unitarios passam sem rede.
- [x] Smoke tests reais podem ser ativados por env vars especificas.
- [x] OmniRoute nao e mais necessario para gerar ideias/roteiros.
