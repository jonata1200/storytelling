# Fase 06 - Evolucao Backend e Escala

## Objetivo

Preparar uma segunda etapa para quando listas em memoria deixarem de ser
suficientes, movendo busca e filtros para queries paginadas.

## Escopo

- Endpoints ou services com parametros de busca.
- Paginacao e limite de resultados.
- Indices ou campos derivados, se necessario.
- Compatibilidade com a UI client-side inicial.

## Checklist de Implementacao

- [x] Medir tamanho medio esperado de listas de projetos e ideias.
- [x] Definir limite para migrar de filtro client-side para backend.
- [x] Criar contrato de parametros para busca de projetos.
- [x] Criar contrato de parametros para busca de ideias.
- [x] Implementar paginacao com `limit` e `offset` ou cursor.
- [x] Adicionar ordenacao no backend.
- [x] Avaliar indices em titulo, status e datas de projeto.
- [x] Avaliar estrutura persistida para ideias salvas se elas continuarem em arquivo runtime.
- [x] Garantir que a UI consiga alternar para resultados paginados.
- [x] Adicionar testes de query e paginacao.
- [x] Documentar limites e comportamento de performance.

## Criterios de Aceite

- [x] A busca continua rapida com centenas ou milhares de itens.
- [x] A UI nao precisa carregar todos os registros para filtrar.
- [x] Ordenacao e filtros retornam resultados determinísticos.
- [x] A primeira versao client-side continua funcionando durante a transicao.

## Validacao Recomendada

- [ ] Criar fixtures com muitos projetos.
- [ ] Criar fixtures com muitas ideias.
- [ ] Medir tempo de resposta das queries.
- [x] `python -m pytest tests/test_search_filters.py -q`
- [x] `ruff check app tests`
- [x] `mypy app tests`
