# ADR 001 — Modos de integração para Meta e Vibes

- Status: proposto, aguardando validação de conta
- Data: 2026-08-26

## Contexto

A aplicação deve migrar texto e recursos visuais para Meta e vídeo para Vibes, preservando os
contratos de domínio e removendo Ollama Cloud/OpenRouter somente no cutover. A disponibilidade
programática dos novos serviços ainda não foi comprovada para as contas do projeto.

## Decisão

1. Meta Text usará exclusivamente API oficial documentada.
2. Meta Image e Vibes Video preferirão API oficial documentada.
3. Playwright poderá ser usado como adapter de contingência somente após confirmação escrita de
   que a automação é permitida para a conta e o uso pretendido.
4. Endpoints privados, tokens extraídos do navegador e engenharia reversa não serão usados.
5. Código de domínio dependerá de contratos/factories, nunca dos adapters concretos.
6. Ollama Cloud e OpenRouter permanecem ativos até os critérios das fases seguintes passarem.

Esta ADR passa a “aceita” somente quando cada linha pendente da tabela abaixo tiver evidência.

| Capability | Integration mode | Estado |
| --- | --- | --- |
| Meta text | API oficial | Pendente de chamada real |
| Meta image | API oficial; Playwright autorizado como fallback | Pendente de acesso/termos |
| Vibes video | API oficial; Playwright autorizado como fallback | Pendente de acesso/termos |

## Segurança operacional

Chaves ficam em variáveis de ambiente ou secret store. Perfis persistentes ficam fora do
repositório em `runtime/browser_profiles/<service>/`. Cookies, tokens, respostas brutas com
dados sensíveis e screenshots autenticados não são versionados.

## Consequências

A Fase 01 pode neutralizar contratos e factories sem alegar que os adapters externos já estão
prontos. As Fases 02–04 não podem declarar aceite de integração antes das chamadas reais e da
decisão sobre automação. Se não houver API nem autorização de navegador para uma capacidade,
ela permanece indisponível e precisa de decisão de produto, não de workaround técnico.
