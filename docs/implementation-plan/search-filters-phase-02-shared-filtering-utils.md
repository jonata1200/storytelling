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

- [x] Criar modulo de utilitarios para busca/filtros na camada de UI ou dominio apropriado.
- [x] Implementar normalizacao case-insensitive.
- [x] Remover acentos na comparacao de busca.
- [x] Ignorar espacos repetidos.
- [x] Implementar helper para buscar em varios campos de um item.
- [x] Implementar helper para comparar datas com fallback seguro.
- [x] Implementar helper para ordenacao alfabetica segura.
- [x] Criar testes para busca com acentos, caixa alta/baixa e termos parciais.
- [x] Criar testes para ordenacao com valores ausentes.
- [x] Garantir que os helpers nao dependam de NiceGUI.

## Criterios de Aceite

- [x] A mesma logica de busca pode ser usada por ideias e projetos.
- [x] Filtros funcionam com dados incompletos sem quebrar a tela.
- [x] Testes unitarios cobrem os casos principais.

## Validacao Recomendada

- [x] `python -m pytest tests/test_search_filters.py -q`
- [x] `ruff check app tests`
- [x] `mypy app tests`
