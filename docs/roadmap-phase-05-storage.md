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

- [ ] Mapear todos os caminhos onde arquivos sao escritos em `storage`.
- [ ] Mapear todos os caminhos onde arquivos sao apagados.
- [ ] Criar servico para calcular uso de storage por projeto.
- [ ] Criar endpoint ou tela de resumo de uso.
- [ ] Definir limite maximo de tamanho para avatar/upload.
- [ ] Definir limite maximo de tamanho para assets gerados.
- [ ] Criar rotina de limpeza de arquivos orfaos com modo dry-run.
- [ ] Criar rotina de limpeza efetiva com validacao de path dentro do storage.
- [ ] Integrar hard delete de projeto com remocao de arquivos associados.
- [ ] Integrar delete de storyboard/video/export com remocao de arquivos associados.
- [ ] Criar testes para arquivos fora do storage.
- [ ] Criar testes para arquivos orfaos.
- [ ] Criar testes para limite de tamanho.
- [ ] Revisar uso direto de `/storage` na UI.

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
