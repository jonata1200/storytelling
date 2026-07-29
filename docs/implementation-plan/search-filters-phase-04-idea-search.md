# Fase 04 - Busca e Filtros em Ideias

## Objetivo

Adicionar busca, filtros e ordenacao no Laboratorio de Ideias para facilitar a
revisao de muitas ideias salvas.

## Escopo

- Pagina `/ideas`.
- Lista "Ideias salvas".
- Filtros por atributos narrativos e metricas.
- Acoes existentes de descartar e desenvolver.

## Checklist de Implementacao

- [ ] Adicionar barra de pesquisa acima da lista de ideias salvas.
- [ ] Buscar por titulo, tema, hook, premissa e protagonista.
- [ ] Adicionar filtro de genero.
- [ ] Adicionar filtro de emocao principal.
- [ ] Adicionar filtro de duracao.
- [ ] Adicionar filtro de complexidade de producao.
- [ ] Adicionar ordenacao por mais recentes.
- [ ] Adicionar ordenacao por potencial de retencao.
- [ ] Adicionar ordenacao por risco de cliche.
- [ ] Adicionar ordenacao por menor complexidade.
- [ ] Adicionar ordenacao A-Z.
- [ ] Mostrar contador de ideias filtradas.
- [ ] Adicionar botao para limpar filtros.
- [ ] Adicionar estado vazio quando nenhuma ideia corresponder aos filtros.
- [ ] Garantir que gerar novas ideias nao perca filtros atuais inesperadamente.

## Criterios de Aceite

- [ ] O usuario consegue encontrar ideias por termos narrativos.
- [ ] Filtros e ordenacao funcionam sem recarregar a pagina.
- [ ] Acoes de descartar e desenvolver continuam funcionando no item filtrado.
- [ ] Estados vazios diferenciam "sem ideias" de "sem resultado".

## Validacao Recomendada

- [ ] Testar busca por titulo, protagonista e premissa.
- [ ] Testar combinacao de genero, emocao e duracao.
- [ ] Testar descarte de item filtrado.
- [ ] `python -m pytest tests/test_idea_lab.py tests/test_project_creation_ui.py -q`
- [ ] `ruff check app tests`
