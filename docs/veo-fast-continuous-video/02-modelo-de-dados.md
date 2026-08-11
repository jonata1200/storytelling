# Fase 2: Modelo de dados para segmentos continuos

## Objetivo

Criar uma estrutura propria para videos continuos, independente de StoryboardFrame, permitindo gerar, pausar, retomar e auditar cada bloco de video.

## Entidades propostas

### ContinuousVideoSegment

Campos sugeridos:

- `id`
- `project_id`
- `segment_number`
- `title`
- `prompt`
- `duration_seconds`
- `status`
- `provider`
- `model`
- `generation_job_id`
- `asset_id`
- `source_segment_id`
- `source_video_asset_id`
- `external_operation_id`
- `request_fingerprint`
- `metadata_json`
- `created_at`
- `updated_at`

### ContinuousVideoPlan

Pode ser uma tabela propria ou metadata em `ProjectProductionSettings`.

Campos sugeridos:

- `project_id`
- `mode`
- `target_duration_seconds`
- `segment_duration_seconds`
- `segment_count`
- `status`
- `metadata_json`

## Checklist

- [x] Criar migration para segmentos continuos.
- [x] Criar models SQLAlchemy.
- [x] Criar schemas de leitura e escrita.
- [x] Criar repository/service para listar segmentos por projeto.
- [x] Criar idempotency key por segmento.
- [x] Criar fingerprint considerando roteiro, Biblioteca Visual, prompt e segmento anterior.
- [x] Registrar custos por segmento.
- [x] Registrar asset gerado por segmento.
- [x] Permitir retomar segmentos com status `failed`, `pending` ou `running` stale.
- [x] Adicionar testes de persistencia e idempotencia.

## Regras

- Segmentos concluidos nao devem ser refeitos automaticamente.
- Segmentos seguintes dependem do segmento anterior quando o modo for continuidade temporal.
- Se um segmento do meio falhar, apenas ele e os seguintes ficam pendentes.

## Resultado esperado

A aplicacao passa a ter uma unidade de trabalho propria para video continuo, separada dos storyboards.
