# Integração Meta — registro de descoberta

## Estado

A interface OpenAI-compatible e structured output da Meta Model API foram confirmados na
documentação pública oficial em 2026-08-26. A URL base, o identificador de modelo liberado para
a conta e uma chamada real continuam pendentes porque o guia operacional exige autenticação.
Este documento não autoriza endpoints privados.

Fonte oficial: <https://ai.meta.com/llama/>.

## Capacidades

| Capacidade | Modo pretendido | Estado | Evidência necessária |
| --- | --- | --- | --- |
| Texto e JSON estruturado | API oficial | Pendente | Chamada real, documentação oficial, modelo e limites |
| Geração de imagem | API oficial, se disponível | Pendente | Acesso da conta e download do arquivo original |
| Geração de imagem | Playwright autorizado, como fallback | Bloqueado por decisão | Confirmação dos termos e autorização da conta |

## Validação de Meta Text

Registrar, sem incluir segredos:

- URL base e endpoint obtidos da documentação oficial;
- identificador exato do modelo e data da validação;
- autenticação e scopes exigidos;
- suporte a JSON estruturado e comportamento para JSON inválido;
- limite de contexto, timeout, rate limit e códigos de erro;
- campos de usage e regra de cálculo de custo;
- request/response sanitizados de uma chamada mínima.

O valor de `META_TEXT_MODEL` só deve ganhar um padrão depois desse teste.

## Validação de imagem

O teste deve cobrir texto para imagem, uma e múltiplas referências, variação de personagem,
local sem personagem, aspect ratios usados pela aplicação e download do original. Medir a
consistência do mesmo rosto em pelo menos três imagens e registrar os metadados aproveitáveis
por `VisualReference`.

## Credenciais e sessão

- Chaves de API devem existir apenas no ambiente/secret store local, nunca no Git.
- `.env.example` pode listar somente nomes de variáveis, com valores vazios.
- Se o fallback de navegador for autorizado, usar um perfil persistente em
  `runtime/browser_profiles/meta/`, que é ignorado pelo Git.
- Cookies, tokens e screenshots não são artefatos de documentação.

## Riscos em aberto

- disponibilidade do produto e do modelo pode variar por conta/região;
- o formato de JSON, usage e custos ainda não foi confirmado;
- automação de navegador pode ser proibida ou quebrar com mudanças da interface;
- ausência de API de imagem exige fallback operacional ainda não escolhido.
