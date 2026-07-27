# Fase 5 - Storage, Retencao e Governanca de Arquivos

## Objetivo

Controlar crescimento do storage local, reduzir arquivos orfaos e tornar assets auditaveis.

## Escopo

- Criar relatorio de uso de storage por projeto.
- Definir tamanho maximo para uploads e assets gerados.
- Criar rotina segura de limpeza de arquivos orfaos.
- Garantir que hard deletes removam arquivos associados quando aplicavel.
- Adicionar politica de retencao configuravel.
- Revisar `StaticFiles` para storage e manter acesso preferencial por `/api/v1/assets/{asset_id}/content`.

## Checklist de acoes

- [x] Mapear todos os caminhos onde arquivos sao escritos em `storage`.
- [x] Mapear todos os caminhos onde arquivos sao apagados.
- [x] Criar servico para calcular uso de storage por projeto.
- [x] Criar endpoint ou tela de resumo de uso.
- [x] Definir limite maximo de tamanho para avatar/upload.
- [x] Definir limite maximo de tamanho para assets gerados.
- [x] Criar rotina de limpeza de arquivos orfaos com modo dry-run.
- [x] Criar rotina de limpeza efetiva com validacao de path dentro do storage.
- [x] Integrar hard delete de projeto com remocao de arquivos associados.
- [ ] Integrar delete de storyboard/video/export com remocao de arquivos associados.
- [x] Criar testes para arquivos fora do storage.
- [x] Criar testes para arquivos orfaos.
- [x] Criar testes para limite de tamanho.
- [x] Revisar uso direto de `/storage` na UI.

## Implementado

- `app/storage/service.py` centraliza resolucao segura de paths, inventario de arquivos locais,
  relatorio de uso por projeto, listagem de orfaos e limpeza com `dry_run`.
- `app/storage/router.py` expoe endpoints privados:
  - `GET /api/v1/storage/usage`
  - `GET /api/v1/storage/projects/{project_id}/usage`
  - `GET /api/v1/storage/orphans`
  - `POST /api/v1/storage/orphans/cleanup?dry_run=true`
- `MAX_UPLOAD_BYTES` e `MAX_GENERATED_ASSET_BYTES` limitam avatar/uploads e assets locais
  registrados.
- `hard_delete_project` coleta `storage_uri` antes de remover o grafo do banco e apaga apenas
  arquivos resolvidos dentro do storage local.

## Pendencias

- Separar deletes especificos de video/export quando houver rotas dedicadas para esses recursos.
- Transformar a auditoria de storage em tela operacional, se fizer sentido para o uso diario.

## Entregaveis

- Servico de auditoria de storage.
- Rotina de limpeza com dry-run.
- Testes para arquivos orfaos e limites de tamanho.
- Tela ou endpoint de resumo de uso.

## Criterios de aceite

- E possivel listar quanto cada projeto ocupa.
- A limpeza informa o que removeria antes de remover.
- Arquivos fora do storage nunca sao removidos ou servidos.
- Projetos apagados nao deixam arquivos grandes sem rastreio.
