# Guia De Modelos Por Provider

## Ollama

Uso recomendado: desenvolvimento local, fallback sem chave externa e testes.

Modelo inicial:

```text
llama3.1:8b
```

Antes de usar:

```powershell
ollama pull llama3.1:8b
```

## Groq

Uso recomendado: baixa latencia para ideias, revisoes e tarefas narrativas.

Modelo inicial:

```text
llama-3.3-70b-versatile
```

Requer `GROQ_API_KEY`.

## NVIDIA NIM

Uso recomendado: hosted endpoint NVIDIA ou NIM local/self-hosted.

Modelo inicial:

```text
openai/gpt-oss-20b
```

`NVIDIA_NIM_API_KEY` e obrigatoria no endpoint hosted
`https://integrate.api.nvidia.com/v1`. Em base URL local, a aplicacao permite
rodar sem chave.

## Fallback

Configure fallback de texto como lista separada por virgula:

```env
TEXT_PROVIDER_FALLBACKS=nvidia_nim,ollama
```

O fallback e usado apenas em falhas transitorias, como timeout, HTTP 429, 5xx ou
erro de rede.
