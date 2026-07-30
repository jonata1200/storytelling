# Troubleshooting De IA

## Texto

- `GROQ_API_KEY nao configurada`: configure a chave na tela de Configuracoes de
  IA ou use `TEXT_PROVIDER=ollama`.
- `NVIDIA_NIM_API_KEY nao configurada`: obrigatoria para
  `https://integrate.api.nvidia.com/v1`; endpoints NIM locais podem rodar sem
  chave.
- Timeout, HTTP 429, 5xx ou erro de rede: habilite `TEXT_PROVIDER_FALLBACKS`
  com uma lista como `nvidia_nim,ollama`.
- Erro de JSON/schema: revise o prompt/modelo. O fallback nao mascara esse tipo
  de erro para nao esconder problema de contrato.

## Imagem E Video

- `Veo AI Free experimental esta desabilitado`: ative `VEO_AI_FREE_ENABLED=true`
  ou pela tela de Configuracoes.
- `Reconecte o Veo AI Free manualmente`: importe novo bundle JSON de cookies.
- Erro de descoberta manual: o provider experimental ainda nao tem endpoint real
  mapeado; use apenas smoke/manual ate a descoberta tecnica ser concluida.

## Segredos

`.runtime/`, cookies, tokens e chaves nao devem ser versionados. Logs e eventos
devem passar por redacao antes de serem exibidos.
