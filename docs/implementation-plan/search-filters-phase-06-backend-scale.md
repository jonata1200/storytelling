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

- [ ] Medir tamanho medio esperado de listas de projetos e ideias.
- [ ] Definir limite para migrar de filtro client-side para backend.
- [ ] Criar contrato de parametros para busca de projetos.
- [ ] Criar contrato de parametros para busca de ideias.
- [ ] Implementar paginacao com `limit` e `offset` ou cursor.
- [ ] Adicionar ordenacao no backend.
- [ ] Avaliar indices em titulo, status e datas de projeto.
- [ ] Avaliar estrutura persistida para ideias salvas se elas continuarem em arquivo runtime.
- [ ] Garantir que a UI consiga alternar para resultados paginados.
- [ ] Adicionar testes de query e paginacao.
- [ ] Documentar limites e comportamento de performance.

## Criterios de Aceite

- [ ] A busca continua rapida com centenas ou milhares de itens.
- [ ] A UI nao precisa carregar todos os registros para filtrar.
- [ ] Ordenacao e filtros retornam resultados determinísticos.
- [ ] A primeira versao client-side continua funcionando durante a transicao.

## Validacao Recomendada

- [ ] Criar fixtures com muitos projetos.
- [ ] Criar fixtures com muitas ideias.
- [ ] Medir tempo de resposta das queries.
- [ ] `python -m pytest tests/test_search_filters.py -q`
- [ ] `ruff check app tests`
- [ ] `mypy app tests`
