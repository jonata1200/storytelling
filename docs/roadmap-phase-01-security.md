# Fase 1 - Seguranca e Fronteiras Publicas

## Objetivo

Definir claramente o que e publico, privado e local-only, reduzindo risco caso a aplicacao seja acessada fora do localhost.

## Escopo

- Revisar a decisao atual de API operacional sem autenticacao.
- Registrar o roteador de autenticacao ou remover codigo legado que sugere auth ativa sem estar em uso.
- Proteger endpoints operacionais por uma dependencia real de usuario/sessao quando `APP_ENV` nao for local/test.
- Separar rotas publicas, como health live, de rotas privadas.
- Revisar o mount direto de `/storage` e preferir acesso por endpoint validado de assets.
- Atualizar README para refletir o comportamento real de login e credenciais.

## Checklist de acoes

- [x] Inventariar todas as rotas em `/api/v1`.
- [x] Classificar cada rota como publica, privada ou local-only.
- [x] Definir comportamento de autenticacao por ambiente: local, test, development e production.
- [x] Decidir se `app.auth.router` sera registrado ou removido.
- [x] Substituir `require_basic_auth` por uma dependencia real ou por dependencia explicitamente local-only.
- [x] Validar tokens/sessoes em rotas privadas.
- [x] Manter `/api/v1/health/live` publico.
- [x] Proteger `/api/v1/health/ready` caso exponha detalhes operacionais sensiveis.
- [x] Revisar o mount de `/storage` em `app.factory`.
- [ ] Adaptar a UI para usar `/api/v1/assets/{asset_id}/content` quando possivel.
- [x] Atualizar testes de autenticacao existentes.
- [x] Adicionar testes para acesso negado em ambiente nao local.
- [x] Atualizar README com o estado real de login e credenciais.

## Entregaveis

- Politica documentada de autenticacao por ambiente.
- Endpoints operacionais protegidos em ambientes nao locais.
- `/storage` removido ou restrito quando nao estiver em ambiente local.
- Testes cobrindo rotas publicas e privadas.
- README alinhado com a implementacao real.

## Criterios de aceite

- `GET /api/v1/health/live` continua publico.
- Endpoints de projeto, assets, storytelling, visual bible, storyboard, video, finalizacao, qualidade e custos exigem autenticacao em ambiente nao local.
- Testes demonstram que ambiente local/test preserva a experiencia esperada.
- Nenhum arquivo fora do storage pode ser servido por endpoint de asset.
