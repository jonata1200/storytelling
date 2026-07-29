# Fase 06 - Qualidade Continua e Dependencias

## Objetivo

Manter a base saudavel no longo prazo, reduzindo surpresa em upgrades e
melhorando a confianca antes de novas funcionalidades.

## Escopo

- Atualizacao planejada de dependencias.
- Pipeline local/CI padronizado.
- Testes de smoke reais controlados.
- Documentacao de arquitetura e operacao.

## Checklist de Implementacao

- [x] Resolver aviso de deprecacao do `fastapi.testclient`/Starlette.
- [x] Avaliar caminho para `httpx2` ou versoes compativeis da stack.
- [x] Atualizar `requirements.lock` em ambiente limpo.
- [x] Rodar `pip check` apos atualizacao.
- [x] Garantir que smoke tests pagos/reais fiquem opt-in por variavel de ambiente.
- [x] Separar testes unitarios, integracao, provider e smoke em comandos documentados.
- [x] Adicionar workflow CI, se ainda nao existir ou se estiver incompleto.
- [x] Fazer CI rodar `ruff`, `mypy` e `pytest` sem provider real.
- [x] Adicionar teste de startup da aplicacao com `create_app(include_ui=False)`.
- [x] Adicionar teste de readiness degradado sem Redis/provider.
- [x] Documentar arquitetura dos dominios principais.
- [x] Documentar fluxo de job de ponta a ponta.
- [x] Documentar troubleshooting de Redis, Postgres, worker e OmniRoute.
- [x] Adicionar checklist de release local.
- [x] Revisar README para refletir a etapa `scenes` separada de `script`.

## Criterios de Aceite

- [x] Ambiente novo consegue rodar setup e testes seguindo a documentacao.
- [x] CI protege lint, tipagem e testes principais.
- [x] Smokes reais nao rodam acidentalmente.
- [x] Avisos de deprecacao conhecidos ficam resolvidos ou documentados.

## Validacao Recomendada

- [x] `pip check`
- [x] `ruff check .`
- [x] `mypy app tests`
- [x] `python -m pytest -q`
