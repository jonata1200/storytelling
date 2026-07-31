# Guia De Modelos Por Provider

## Ollama Cloud

Uso recomendado: modelo na nuvem com chave `OLLAMA_API_KEY`, sem instalar o
Ollama na maquina.

Modelos mantidos na aplicacao:

```text
gpt-oss:120b
gpt-oss:20b
```

Configuracao:

```env
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_API_KEY=sua_chave_ollama_cloud
OLLAMA_DEFAULT_MODEL=gpt-oss:120b
```

## Ollama Local

Uso recomendado: desenvolvimento local quando voce quiser rodar um dos modelos
selecionados na propria maquina.

Modelo inicial:

```text
gpt-oss:20b
```

Antes de usar localmente:

```powershell
ollama pull gpt-oss:20b
```

```env
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_API_KEY=ollama
OLLAMA_DEFAULT_MODEL=gpt-oss:20b
```

## Groq

Uso recomendado: baixa latencia para ideias, revisoes e tarefas narrativas.

Modelos mantidos na aplicacao:

```text
openai/gpt-oss-120b
qwen/qwen3.6-27b
openai/gpt-oss-20b
```

Requer `GROQ_API_KEY`.

## NVIDIA NIM

Uso recomendado: hosted endpoint NVIDIA ou NIM local/self-hosted.

Modelos mantidos na aplicacao:

```text
nvidia/nemotron-3-super-120b-a12b
openai/gpt-oss-120b
nvidia/llama-3.3-nemotron-super-49b-v1.5
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
