# Fase 02 - Camada Generica Para Texto OpenAI-Compatible

## Objetivo

Criar uma camada unica para chamadas de texto via `/chat/completions`, reutilizada
por Ollama, Groq e NVIDIA NIM.

## Arquitetura Proposta

Criar um provider base:

```text
app/providers/llm/openai_compatible.py
```

Responsabilidades:

- Montar `POST {base_url}/chat/completions`.
- Enviar `Authorization: Bearer {api_key}` quando provider exigir chave.
- Permitir api key fake para Ollama local.
- Suportar `response_format={"type":"json_object"}` quando aceito.
- Fazer retry sem `response_format` em HTTP 400/422.
- Interpretar resposta JSON normal e SSE.
- Reaproveitar parsing JSON robusto hoje existente no provider OmniRoute.
- Padronizar erros com nome do provider real.

## Checklist

- [x] Criar `OpenAICompatibleLLMProvider`.
- [x] Extrair parsing de JSON/stream do provider atual para helper reutilizavel.
- [x] Criar tipo de configuracao por provider: `provider_name`, `base_url`, `api_key`, `model`.
- [x] Permitir providers sem chave obrigatoria, caso de Ollama local.
- [x] Adicionar timeout por tarefa.
- [x] Preservar recuperacao de resposta com JSON embutido.
- [x] Preservar recuperacao de roteiro em texto quando aplicavel.
- [x] Testar retry sem `response_format`.
- [x] Testar erro HTTP com redacao de segredo.
- [x] Testar timeout e erro de rede.

## Env Vars Propostas

```env
TEXT_PROVIDER=groq
TEXT_PROVIDER_FALLBACKS=nvidia_nim,ollama
```

## Criterios De Saida

- [x] Provider generico passa em testes unitarios.
- [x] Nenhum provider real externo e chamado em testes unitarios.
- [x] A camada generica consegue substituir o provider OmniRoute para texto.
- [x] `run_structured_generation` continua sem conhecer detalhes dos providers.
