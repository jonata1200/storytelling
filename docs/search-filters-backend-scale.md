# Busca e filtros - backend e escala

## Limite de migracao

A UI atual filtra client-side para manter a experiencia instantanea em listas
pequenas. A troca para backend paginado deve acontecer quando qualquer lista
ultrapassar aproximadamente:

- 200 projetos carregados na home ou em `/projects`;
- 300 ideias salvas no Laboratorio de Ideias;
- 150 ideias de historia dentro de um unico projeto.

Esses limites evitam carregar muitos cards e mantem a digitacao fluida em
desktop e mobile.

## Projetos

Endpoint paginado:

```text
GET /api/v1/projects/search
```

Parametros:

- `query`: busca em titulo, descricao e status.
- `status_filter`: `all`, `draft`, `active`, `review`, `done`, `blocked`.
- `stage_filter`: `all`, `script`, `scenes`, `visual`, `storyboard`, `video`,
  `finalization`, `quality`.
- `updated_period`: `any`, `7`, `30`.
- `sort`: `updated_desc`, `created_desc`, `title_asc`.
- `limit`: 1 a 200.
- `offset`: 0 ou maior.

Resposta:

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

## Ideias de projeto

Endpoint paginado:

```text
GET /api/v1/storytelling/projects/{project_id}/ideas/search
```

Parametros:

- `query`: busca em titulo, tema, hook, premissa e protagonista.
- `genre_filter`: `all` ou genero.
- `emotion_filter`: `all` ou emocao principal.
- `duration_filter`: `all` ou duracao em minutos.
- `complexity_filter`: `all`, `low`, `medium`, `high`.
- `sort`: `created_desc`, `retention_desc`, `cliche_asc`, `complexity_asc`,
  `title_asc`.
- `limit`: 1 a 200.
- `offset`: 0 ou maior.

## Indices avaliados

Projetos ja possuem chave primaria e timestamps. Para alto volume, considerar:

- indice em `projects.updated_at`;
- indice em `projects.created_at`;
- indice funcional em `lower(projects.title)`;
- indice composto em `(status, updated_at)`.

Ideias de projeto possuem `project_id` indexado. Para filtros pesados por
genero, emocao e duracao, considerar promover esses campos do `payload` para
colunas dedicadas ou indices JSONB especificos em Postgres.

## Ideias salvas do laboratorio

As ideias salvas do Laboratorio de Ideias continuam em arquivo runtime na
primeira versao. Quando passarem do limite recomendado, migrar para tabela
persistida com:

- `title`, `genre`, `primary_emotion`, `duration_minutes`;
- `retention_potential`, `cliche_risk`, `production_complexity`;
- `payload`;
- `created_at`, `updated_at`.

## Compatibilidade da UI

A UI client-side continua sendo a fonte da primeira experiencia. A migracao para
backend deve preservar os mesmos nomes de filtros e ordenacoes para permitir uma
troca gradual por tela.
