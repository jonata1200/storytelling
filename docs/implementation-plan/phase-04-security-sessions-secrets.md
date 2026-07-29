# Fase 04 - Seguranca, Sessoes e Segredos

## Objetivo

Endurecer a aplicacao para uso alem do ambiente local, protegendo sessoes,
acoes sensiveis, segredos de provider e configuracoes runtime.

## Escopo

- Sessao revogavel.
- Cookies por ambiente.
- Protecao CSRF para a UI.
- Tratamento seguro de API keys em preferencias.
- Auditoria de login/configuracao.

## Checklist de Implementacao

- [x] Criar modelo/tabela de sessoes persistidas com expiracao e revogacao.
- [x] Substituir token puramente HMAC por session id revogavel.
- [x] Adicionar logout que invalida a sessao no servidor.
- [x] Revisar flags de cookie: `HttpOnly`, `Secure`, `SameSite`.
- [x] Definir comportamento diferente para `local`, `development`, `test` e producao.
- [x] Adicionar protecao CSRF para acoes mutantes da UI.
- [x] Auditar endpoints mutantes que dependem apenas de cookie.
- [x] Remover API key das preferencias em texto puro ou criptografar em repouso.
- [x] Avaliar Windows DPAPI, keyring local ou manter segredos apenas em env.
- [x] Redigir segredos tambem em payloads de configuracao salvos/logados.
- [x] Emitir evento operacional para login, logout e alteracao de provider/modelo.
- [x] Adicionar rate limit simples para login e cadastro.
- [x] Adicionar testes de sessao expirada, revogada e cookie invalido.
- [x] Adicionar testes de CSRF para rotas/acoes mutantes.
- [x] Atualizar README com orientacoes de producao.

## Criterios de Aceite

- [x] Sessao pode ser invalidada sem trocar `APP_SECRET_KEY`.
- [x] API keys nao ficam expostas em arquivo runtime sem protecao.
- [x] Acoes mutantes da UI exigem protecao adequada.
- [x] Testes de seguranca passam.

## Validacao Recomendada

- [x] `python -m pytest tests/test_auth.py tests/test_security_regressions.py -q`
- [x] `python -m pytest tests/test_provider_policy.py tests/test_settings.py -q`
- [x] `ruff check .`
- [x] `mypy app tests`
- [x] `python -m pytest -q`
