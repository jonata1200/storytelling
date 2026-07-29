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

- [x] Adicionar barra de pesquisa acima da lista de ideias salvas.
- [x] Buscar por titulo, tema, hook, premissa e protagonista.
- [x] Adicionar filtro de genero.
- [x] Adicionar filtro de emocao principal.
- [x] Adicionar filtro de duracao.
- [x] Adicionar filtro de complexidade de producao.
- [x] Adicionar ordenacao por mais recentes.
- [x] Adicionar ordenacao por potencial de retencao.
- [x] Adicionar ordenacao por risco de cliche.
- [x] Adicionar ordenacao por menor complexidade.
- [x] Adicionar ordenacao A-Z.
- [x] Mostrar contador de ideias filtradas.
- [x] Adicionar botao para limpar filtros.
- [x] Adicionar estado vazio quando nenhuma ideia corresponder aos filtros.
- [x] Garantir que gerar novas ideias nao perca filtros atuais inesperadamente.

## Criterios de Aceite

- [x] O usuario consegue encontrar ideias por termos narrativos.
- [x] Filtros e ordenacao funcionam sem recarregar a pagina.
- [x] Acoes de descartar e desenvolver continuam funcionando no item filtrado.
- [x] Estados vazios diferenciam "sem ideias" de "sem resultado".

## Validacao Recomendada

- [x] Testar busca por titulo, protagonista e premissa.
- [x] Testar combinacao de genero, emocao e duracao.
- [x] Testar descarte de item filtrado.
- [x] `python -m pytest tests/test_idea_lab.py tests/test_project_creation_ui.py -q`
- [x] `ruff check app tests`
