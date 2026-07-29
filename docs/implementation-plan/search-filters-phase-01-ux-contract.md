# Fase 01 - Contrato de UX e Dados

## Objetivo

Definir exatamente como a busca e os filtros devem funcionar nas telas de
ideias e projetos antes de alterar a interface.

## Escopo

- Mapear os campos disponiveis em projetos e ideias.
- Definir criterios de busca textual.
- Definir filtros e ordenacoes da primeira versao.
- Preservar uma experiencia simples para quem tem poucos itens.

## Checklist de Implementacao

- [ ] Mapear os campos renderizados nos cards de projeto.
- [ ] Mapear os campos renderizados nos cards de ideia.
- [ ] Definir busca textual de projetos por titulo, status e metadados disponiveis.
- [ ] Definir busca textual de ideias por titulo, tema, hook, premissa e protagonista.
- [ ] Definir filtros de projeto: status, etapa e periodo de atualizacao.
- [ ] Definir filtros de ideia: genero, emocao, duracao e complexidade.
- [ ] Definir ordenacao de projeto: recentes, atualizados recentemente e A-Z.
- [ ] Definir ordenacao de ideia: recentes, retencao, risco de cliche, complexidade e A-Z.
- [ ] Definir texto dos estados vazios para nenhum resultado encontrado.
- [ ] Definir comportamento do botao de limpar filtros.

## Criterios de Aceite

- [ ] O comportamento esperado de cada filtro esta documentado.
- [ ] A busca nao exige mudanca de banco na primeira versao.
- [ ] A UI proposta cabe em desktop e mobile sem poluir as telas.

## Validacao Recomendada

- [ ] Revisar o plano com dados reais de projetos e ideias existentes.
- [ ] Conferir se todos os campos usados existem no payload atual.
