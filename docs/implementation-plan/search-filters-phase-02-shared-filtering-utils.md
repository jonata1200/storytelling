# Fase 02 - Utilitarios Compartilhados de Busca

## Objetivo

Criar funcoes reutilizaveis para normalizar texto, filtrar listas e ordenar
resultados sem duplicar logica entre ideias e projetos.

## Escopo

- Normalizacao de texto para busca tolerante.
- Helpers de match por campos multiplos.
- Ordenacao deterministica.
- Testes unitarios dos filtros.

## Checklist de Implementacao

- [ ] Criar modulo de utilitarios para busca/filtros na camada de UI ou dominio apropriado.
- [ ] Implementar normalizacao case-insensitive.
- [ ] Remover acentos na comparacao de busca.
- [ ] Ignorar espacos repetidos.
- [ ] Implementar helper para buscar em varios campos de um item.
- [ ] Implementar helper para comparar datas com fallback seguro.
- [ ] Implementar helper para ordenacao alfabetica segura.
- [ ] Criar testes para busca com acentos, caixa alta/baixa e termos parciais.
- [ ] Criar testes para ordenacao com valores ausentes.
- [ ] Garantir que os helpers nao dependam de NiceGUI.

## Criterios de Aceite

- [ ] A mesma logica de busca pode ser usada por ideias e projetos.
- [ ] Filtros funcionam com dados incompletos sem quebrar a tela.
- [ ] Testes unitarios cobrem os casos principais.

## Validacao Recomendada

- [ ] `python -m pytest tests/test_search_filters.py -q`
- [ ] `ruff check app tests`
- [ ] `mypy app tests`
