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

- [ ] Adicionar barra de pesquisa no topo da pagina `/projects`.
- [ ] Adicionar filtro de status do projeto.
- [ ] Adicionar filtro de etapa atual ou progresso, usando os dados ja disponiveis.
- [ ] Adicionar filtro de periodo de atualizacao.
- [ ] Adicionar select de ordenacao.
- [ ] Aplicar filtros na lista carregada em memoria.
- [ ] Mostrar contador de resultados filtrados.
- [ ] Adicionar botao para limpar filtros.
- [ ] Adicionar estado vazio quando nenhum projeto corresponder aos filtros.
- [ ] Reutilizar a mesma logica na secao "Projetos recentes" do dashboard.
- [ ] Garantir que o card "Criar novo projeto" continue sempre disponivel.
- [ ] Ajustar layout responsivo para mobile.

## Criterios de Aceite

- [ ] O usuario consegue encontrar projeto por texto parcial.
- [ ] Filtros podem ser combinados sem quebrar a lista.
- [ ] Limpar filtros restaura todos os projetos.
- [ ] A tela continua simples quando ha poucos projetos.

## Validacao Recomendada

- [ ] Testar com zero projetos.
- [ ] Testar com poucos projetos.
- [ ] Testar com muitos projetos e nomes semelhantes.
- [ ] `python -m pytest tests/test_project_creation_ui.py tests/test_project_creation_workspace.py -q`
- [ ] `ruff check app tests`
