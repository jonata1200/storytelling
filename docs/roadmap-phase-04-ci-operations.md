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

- [x] Escolher ferramenta de lockfile: `uv`, `pip-tools` ou equivalente.
- [x] Gerar lockfile a partir do `pyproject.toml`.
- [x] Documentar instalacao usando lockfile.
- [x] Criar workflow de CI.
- [x] Configurar servico PostgreSQL com pgvector no CI.
- [x] Configurar servico Redis no CI.
- [x] Executar `ruff check .` no CI.
- [x] Executar `python -m pytest` no CI.
- [x] Executar `mypy app tests` no CI.
- [x] Executar `alembic upgrade head` em banco limpo no CI.
- [x] Testar criacao minima da app em modo sem UI.
- [x] Revisar warning do `TestClient`.
- [x] Atualizar README com comandos oficiais.
- [x] Atualizar scripts de execucao se necessario.

## Pendencias conhecidas

- [ ] Migrar do `TestClient` atual quando a stack FastAPI/Starlette concluir a transicao para `httpx2`.
- [ ] Considerar migrar o lock de `requirements.lock` para uma ferramenta com hashes, como `uv.lock`, se o projeto exigir reprodutibilidade criptografica.

## Entregaveis

- Lockfile versionado.
- Pipeline de CI.
- Documentacao atualizada.
- Teste automatizado de migrations em banco limpo.

## Criterios de aceite

- Um clone novo consegue instalar e rodar testes com comandos documentados.
- CI falha se `ruff`, `pytest`, `mypy` ou migrations quebrarem.
- Versoes de dependencias ficam travadas e atualizadas por processo explicito.
