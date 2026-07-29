# Contrato de UX - Busca e filtros

Este contrato define a primeira versao da busca de ideias e projetos. A
implementacao inicial sera client-side, usando listas ja carregadas pela UI, sem
alterar banco, migrations ou endpoints.

## Projetos

### Campos disponiveis

- `title`: texto principal do card.
- `description`: texto secundario do card, com fallback para "Projeto em desenvolvimento".
- `status`: estado atual do workflow.
- `created_at`: data de criacao herdada do mixin de timestamps.
- `updated_at`: data de ultima atualizacao herdada do mixin de timestamps.
- `current_version`: versao atual do projeto.

### Busca textual

A busca de projetos deve procurar em:

- titulo;
- descricao;
- status normalizado.

A comparacao deve ignorar maiusculas/minusculas, acentos e espacos repetidos.
Todos os termos digitados precisam estar presentes em algum dos campos
pesquisaveis.

### Filtros

- Status: todos, rascunho, em andamento, revisao, concluido, falha/arquivado.
- Etapa: todos, roteiro, cenas, visual, storyboard, video, finalizacao.
- Atualizacao: qualquer periodo, ultimos 7 dias, ultimos 30 dias.

Na primeira versao, etapa pode ser derivada de `ProjectStatus`, sem consultar
contagens detalhadas do workspace.

### Ordenacao

- Mais recentes: `created_at` decrescente.
- Atualizados recentemente: `updated_at` decrescente.
- Nome A-Z: `title` crescente.

### Estados vazios

- Sem projetos: manter o estado atual "Nenhum projeto criado ainda".
- Sem resultado filtrado: exibir "Nenhum projeto encontrado para esses filtros"
  e oferecer acao para limpar filtros.

## Ideias

### Campos disponiveis

Ideias salvas sao dicionarios normalizados pelo Idea Lab. A primeira versao deve
usar:

- `title`;
- `theme`;
- `hook`;
- `premise`;
- `protagonist`;
- `genre`;
- `primary_emotion`;
- `duration_minutes`;
- `retention_potential`;
- `cliche_risk`;
- `production_complexity`;
- `created_at`.

### Busca textual

A busca de ideias deve procurar em:

- titulo;
- tema;
- hook;
- premissa;
- protagonista.

A comparacao deve ignorar maiusculas/minusculas, acentos e espacos repetidos.
Todos os termos digitados precisam estar presentes em algum dos campos
pesquisaveis.

### Filtros

- Genero: todos ou um genero especifico.
- Emocao principal: todas ou uma emocao especifica.
- Duracao: todas ou uma duracao especifica em minutos.
- Complexidade: todas, baixa, media, alta.

### Ordenacao

- Mais recentes: `created_at` decrescente.
- Melhor retencao: `retention_potential` decrescente.
- Menor risco de cliche: `cliche_risk` crescente.
- Menor complexidade: `production_complexity` crescente.
- Nome A-Z: `title` crescente.

### Estados vazios

- Sem ideias: manter "Nenhuma ideia salva ainda".
- Sem resultado filtrado: exibir "Nenhuma ideia encontrada para esses filtros"
  e oferecer acao para limpar filtros.

## Layout

- Desktop: barra de busca larga, seguida por filtros compactos em linha.
- Mobile: controles quebram em linhas, mantendo busca em largura total.
- O botao de limpar filtros deve aparecer quando houver algum filtro ativo.
- O contador deve diferenciar total carregado e total filtrado.

## Regras de implementacao

- A primeira versao nao deve alterar banco.
- Helpers de busca nao devem importar NiceGUI.
- A UI deve reutilizar os mesmos helpers para ideias e projetos.
- Valores ausentes nao devem quebrar busca, filtro ou ordenacao.
