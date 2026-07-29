# Fase 03 - Busca e Filtros em Projetos

## Objetivo

Adicionar barra de pesquisa, filtros e ordenacao na listagem de projetos para
facilitar navegacao quando houver muitos projetos.

## Escopo

- Pagina `/projects`.
- Secao "Projetos recentes" no dashboard.
- Estado vazio para filtros sem resultado.
- Preservar cards e acoes existentes.

## Checklist de Implementacao

- [x] Adicionar barra de pesquisa no topo da pagina `/projects`.
- [x] Adicionar filtro de status do projeto.
- [x] Adicionar filtro de etapa atual ou progresso, usando os dados ja disponiveis.
- [x] Adicionar filtro de periodo de atualizacao.
- [x] Adicionar select de ordenacao.
- [x] Aplicar filtros na lista carregada em memoria.
- [x] Mostrar contador de resultados filtrados.
- [x] Adicionar botao para limpar filtros.
- [x] Adicionar estado vazio quando nenhum projeto corresponder aos filtros.
- [x] Reutilizar a mesma logica na secao "Projetos recentes" do dashboard.
- [x] Garantir que o card "Criar novo projeto" continue sempre disponivel.
- [x] Ajustar layout responsivo para mobile.

## Criterios de Aceite

- [x] O usuario consegue encontrar projeto por texto parcial.
- [x] Filtros podem ser combinados sem quebrar a lista.
- [x] Limpar filtros restaura todos os projetos.
- [x] A tela continua simples quando ha poucos projetos.

## Validacao Recomendada

- [x] Testar com zero projetos.
- [x] Testar com poucos projetos.
- [x] Testar com muitos projetos e nomes semelhantes.
- [x] `python -m pytest tests/test_project_creation_ui.py tests/test_project_creation_workspace.py -q`
- [x] `ruff check app tests`
