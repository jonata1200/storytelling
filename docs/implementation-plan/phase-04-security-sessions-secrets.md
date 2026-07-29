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

- [ ] Criar modelo/tabela de sessoes persistidas com expiração e revogacao.
- [ ] Substituir token puramente HMAC por session id revogavel.
- [ ] Adicionar logout que invalida a sessao no servidor.
- [ ] Revisar flags de cookie: `HttpOnly`, `Secure`, `SameSite`.
- [ ] Definir comportamento diferente para `local`, `development`, `test` e producao.
- [ ] Adicionar protecao CSRF para acoes mutantes da UI.
- [ ] Auditar endpoints mutantes que dependem apenas de cookie.
- [ ] Remover API key das preferencias em texto puro ou criptografar em repouso.
- [ ] Avaliar Windows DPAPI, keyring local ou manter segredos apenas em env.
- [ ] Redigir segredos tambem em payloads de configuracao salvos/logados.
- [ ] Emitir evento operacional para login, logout e alteracao de provider/modelo.
- [ ] Adicionar rate limit simples para login e cadastro.
- [ ] Adicionar testes de sessao expirada, revogada e cookie invalido.
- [ ] Adicionar testes de CSRF para rotas/acoes mutantes.
- [ ] Atualizar README com orientacoes de producao.

## Criterios de Aceite

- [ ] Sessao pode ser invalidada sem trocar `APP_SECRET_KEY`.
- [ ] API keys nao ficam expostas em arquivo runtime sem protecao.
- [ ] Acoes mutantes da UI exigem protecao adequada.
- [ ] Testes de seguranca passam.

## Validacao Recomendada

- [ ] `python -m pytest tests/test_auth.py tests/test_security_regressions.py -q`
- [ ] `python -m pytest tests/test_provider_policy.py tests/test_settings.py -q`
- [ ] `ruff check .`
- [ ] `mypy app tests`
- [ ] `python -m pytest -q`
