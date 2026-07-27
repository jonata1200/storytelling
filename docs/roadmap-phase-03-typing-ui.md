# Fase 3 - Tipagem, Organizacao da UI e Qualidade Estatica

## Objetivo

Fazer `mypy app tests` passar e reduzir acoplamento dinamico dificil de manter.

## Escopo

- Substituir pontes baseadas em `sys.modules` por injecao explicita ou objetos de contexto tipados.
- Criar `Protocol` ou dataclasses para callbacks de UI.
- Corrigir helpers que retornam `object` e depois sao chamados como funcoes.
- Corrigir expressoes SQL que usam `where(... if ... else False)`.
- Quebrar arquivos grandes de UI em componentes menores.
- Preservar comportamento atual com testes antes de cada extracao maior.

## Checklist de acoes

- [ ] Executar `mypy app tests --no-incremental` e salvar lista atual de erros.
- [ ] Agrupar erros por causa raiz.
- [ ] Criar contratos tipados para callbacks de UI.
- [ ] Substituir `_page_attr` por injecao explicita ou contexto tipado.
- [ ] Substituir `_service_attr` por injecao explicita ou contexto tipado.
- [ ] Corrigir chamadas onde mypy enxerga `object` como callable.
- [ ] Corrigir expressoes SQL que retornam `BinaryExpression[bool] | bool`.
- [ ] Corrigir casts de UUID e valores opcionais em handlers de UI.
- [ ] Extrair componentes menores de `app/ui/workspace/storyboard_video_area.py`.
- [ ] Extrair componentes menores de `app/ui/workspace/assets_area.py`.
- [ ] Reduzir responsabilidade de `app/ui/pages.py`.
- [ ] Reduzir responsabilidade de `app/ui/routes/settings_page.py`.
- [ ] Revisar `# noqa: F401` usados como cola arquitetural.
- [ ] Rodar `ruff check .`.
- [ ] Rodar `python -m pytest`.
- [ ] Rodar `mypy app tests`.

## Entregaveis

- `mypy app tests` passando.
- Menos uso de `Any`, `object` callable e `# noqa: F401` como cola arquitetural.
- Componentes de UI com contratos explicitos.
- Testes mantidos ou ampliados nas areas refatoradas.

## Criterios de aceite

- `ruff check .` passa.
- `python -m pytest` passa.
- `mypy app tests` passa sem `--ignore-errors`.
- Refatoracoes nao alteram fluxo visual ou rotas existentes sem decisao explicita.
