# Guia De Modelos Por Provider

## Ollama Cloud

Uso recomendado: modelo na nuvem com chave `OLLAMA_API_KEY`, sem instalar o
Ollama na maquina.

Modelo inicial:

```text
gpt-oss:120b
```

Configuracao:

```env
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_API_KEY=sua_chave_ollama_cloud
OLLAMA_DEFAULT_MODEL=gpt-oss:120b
```

## Ollama Local

Uso recomendado: desenvolvimento local, fallback sem chave externa e testes.

Modelo inicial:

```text
llama3.1:8b
```

Antes de usar localmente:

```powershell
ollama pull llama3.1:8b
```

```env
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_API_KEY=ollama
OLLAMA_DEFAULT_MODEL=llama3.1:8b
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
