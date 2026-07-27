# Fase 6 - Custos, Orcamentos e Limites de Uso

## Objetivo

Dar previsibilidade ao uso de OpenRouter e evitar gastos acidentais.

## Escopo

- Modelar custo estimado por provider/modelo/operacao.
- Definir orcamento por projeto e por etapa.
- Exibir estimativa antes de gerar lotes de imagem/video.
- Bloquear ou exigir confirmacao quando passar do limite.
- Registrar custo real retornado pelo provider e comparar com estimativa.
- Melhorar observabilidade de custo acumulado por projeto.

## Checklist de acoes

- [x] Mapear operacoes pagas atuais: texto, imagem e video.
- [x] Definir tabela/configuracao de custo por provider, modelo e operacao.
- [x] Criar estimador de custo para texto.
- [x] Criar estimador de custo para imagem.
- [x] Criar estimador de custo para video.
- [x] Definir orcamento por projeto.
- [x] Definir limite opcional por etapa.
- [ ] Exibir estimativa antes de gerar storyboards em lote.
- [x] Exibir estimativa antes de gerar videos em lote.
- [x] Exigir confirmacao quando estimativa passar do limite.
- [x] Registrar custo real retornado pelo provider.
- [x] Comparar custo estimado versus custo real.
- [x] Criar resumo por projeto, etapa, provider e modelo.
- [x] Adicionar testes de limite e bloqueio.

## Implementado

- `app/costs/service.py` define politica padrao por operacao:
  `text_generation`, `image_generation`, `image_edit`, `image_to_video`,
  `text_to_video` e `speech_generation`.
- Endpoints privados adicionados:
  - `GET /api/v1/costs/policies`
  - `POST /api/v1/costs/operation-estimate`
  - `GET /api/v1/costs/projects/{project_id}/budget`
  - `PATCH /api/v1/costs/projects/{project_id}/budget`
  - `POST /api/v1/costs/budget-check`
  - `GET /api/v1/costs/projects/{project_id}/summary`
- Orcamentos sao armazenados em `project_production_settings.metadata_json` usando
  `cost_budget_usd` e `cost_stage_budgets_usd`, evitando migracao de banco nesta fase.
- A geracao de video calcula a estimativa do lote antes da chamada externa e bloqueia a
  operacao quando o projeto ou a etapa `video` excede o limite configurado.
- O resumo compara estimado, real e credito por projeto, etapa, provider e modelo.

## Pendencias

- Levar a estimativa de storyboard para a interface antes da geracao de imagens em lote.
- Substituir a tabela padrao por precos sincronizados por modelo quando o provider expuser
  catalogo confiavel de precos.

## Entregaveis

- Politica de orcamento por projeto.
- Estimativa antes de chamadas caras.
- Registro de custo estimado versus real.
- Alertas de limite atingido.

## Criterios de aceite

- Usuario ve custo estimado antes de gerar video em lote.
- Operacoes caras respeitam limite configurado.
- Relatorio de custos mostra total por etapa, provider e modelo.
