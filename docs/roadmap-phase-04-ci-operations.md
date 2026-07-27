# Fase 4 - Reprodutibilidade, CI e Operacao

## Objetivo

Garantir que instalacao, testes e deploy sejam previsiveis entre maquinas.

## Escopo

- Adotar lockfile de dependencias, por exemplo `uv.lock` ou `requirements.lock`.
- Criar workflow de CI para instalar dependencias, executar checks e validar migrations.
- Adicionar checagem de que `alembic upgrade head` funciona em banco limpo.
- Documentar comandos de desenvolvimento e producao.
- Revisar warning de deprecacao do `TestClient` e planejar migracao quando a stack exigir.

## Checklist de acoes

- [ ] Escolher ferramenta de lockfile: `uv`, `pip-tools` ou equivalente.
- [ ] Gerar lockfile a partir do `pyproject.toml`.
- [ ] Documentar instalacao usando lockfile.
- [ ] Criar workflow de CI.
- [ ] Configurar servico PostgreSQL com pgvector no CI.
- [ ] Configurar servico Redis no CI.
- [ ] Executar `ruff check .` no CI.
- [ ] Executar `python -m pytest` no CI.
- [ ] Executar `mypy app tests` no CI.
- [ ] Executar `alembic upgrade head` em banco limpo no CI.
- [ ] Testar criacao minima da app em modo sem UI.
- [ ] Revisar warning do `TestClient`.
- [ ] Atualizar README com comandos oficiais.
- [ ] Atualizar scripts de execucao se necessario.

## Entregaveis

- Lockfile versionado.
- Pipeline de CI.
- Documentacao atualizada.
- Teste automatizado de migrations em banco limpo.

## Criterios de aceite

- Um clone novo consegue instalar e rodar testes com comandos documentados.
- CI falha se `ruff`, `pytest`, `mypy` ou migrations quebrarem.
- Versoes de dependencias ficam travadas e atualizadas por processo explicito.
