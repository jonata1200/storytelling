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

- [ ] Resolver aviso de deprecacao do `fastapi.testclient`/Starlette.
- [ ] Avaliar caminho para `httpx2` ou versoes compativeis da stack.
- [ ] Atualizar `requirements.lock` em ambiente limpo.
- [ ] Rodar `pip check` apos atualizacao.
- [ ] Garantir que smoke tests pagos/reais fiquem opt-in por variavel de ambiente.
- [ ] Separar testes unitarios, integracao, provider e smoke em comandos documentados.
- [ ] Adicionar workflow CI, se ainda nao existir ou se estiver incompleto.
- [ ] Fazer CI rodar `ruff`, `mypy` e `pytest` sem provider real.
- [ ] Adicionar teste de startup da aplicacao com `create_app(include_ui=False)`.
- [ ] Adicionar teste de readiness degradado sem Redis/provider.
- [ ] Documentar arquitetura dos dominios principais.
- [ ] Documentar fluxo de job de ponta a ponta.
- [ ] Documentar troubleshooting de Redis, Postgres, worker e OmniRoute.
- [ ] Adicionar checklist de release local.
- [ ] Revisar README para refletir a etapa `scenes` separada de `script`.

## Criterios de Aceite

- [ ] Ambiente novo consegue rodar setup e testes seguindo a documentacao.
- [ ] CI protege lint, tipagem e testes principais.
- [ ] Smokes reais nao rodam acidentalmente.
- [ ] Avisos de deprecacao conhecidos ficam resolvidos ou documentados.

## Validacao Recomendada

- [ ] `pip check`
- [ ] `ruff check .`
- [ ] `mypy app tests`
- [ ] `python -m pytest -q`
