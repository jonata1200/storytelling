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

- [ ] Adicionar settings `ollama_base_url`, `ollama_api_key`, `ollama_default_model`.
- [ ] Permitir `OLLAMA_API_KEY=ollama` como valor padrao local.
- [ ] Criar provider `OllamaLLMProvider`.
- [ ] Testar chamada local mockada para `/chat/completions`.
- [ ] Documentar necessidade de rodar `ollama serve`.
- [ ] Documentar necessidade de baixar o modelo localmente.

## Checklist Groq

- [ ] Adicionar settings `groq_base_url`, `groq_api_key`, `groq_default_model`.
- [ ] Criar provider `GroqLLMProvider`.
- [ ] Validar `GROQ_API_KEY` obrigatoria.
- [ ] Definir lista inicial de modelos Groq selecionaveis.
- [ ] Testar tratamento de rate limit e quota.

## Checklist NVIDIA NIM

- [ ] Adicionar settings `nvidia_nim_base_url`, `nvidia_nim_api_key`, `nvidia_nim_default_model`.
- [ ] Criar provider `NvidiaNimLLMProvider`.
- [ ] Suportar hosted endpoint `https://integrate.api.nvidia.com/v1`.
- [ ] Permitir base URL local para NIM self-hosted.
- [ ] Definir lista inicial de modelos NVIDIA selecionaveis.
- [ ] Testar provider com resposta mockada.

## Checklist Comum

- [ ] Atualizar `SUPPORTED_AI_PROVIDERS`.
- [ ] Atualizar `provider_display_name`.
- [ ] Atualizar `provider_api_key`.
- [ ] Atualizar `provider_model`.
- [ ] Atualizar `provider_base_url`.
- [ ] Atualizar readiness para texto.
- [ ] Atualizar testes de settings e provider policy.

## Criterios De Saida

- [ ] A aplicacao consegue selecionar qualquer um dos tres providers para texto.
- [ ] Testes unitarios passam sem rede.
- [ ] Smoke tests reais podem ser ativados por env vars especificas.
- [ ] OmniRoute nao e mais necessario para gerar ideias/roteiros.
