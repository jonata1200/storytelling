# Fase 05 - Storage, Custos e Escala

## Objetivo

Preparar storage e custos para projetos maiores, evitando varreduras caras,
arquivos orfaos invisiveis e estimativas pouco auditaveis.

## Escopo

- Indice persistente de uso de storage.
- Governanca de assets e orfaos.
- Custos por provider/modelo/operacao mais realistas.
- Relatorio por etapa e projeto.

## Checklist de Implementacao

- [x] Criar campos ou tabela para armazenar tamanho dos assets no momento da criacao.
- [x] Atualizar criacao de imagens, video e audio para gravar `size_bytes`.
- [x] Evitar depender de `rglob("*")` em consultas frequentes de uso.
- [x] Manter varredura completa como acao administrativa sob demanda.
- [x] Adicionar job de reconciliacao de storage local.
- [x] Marcar assets ausentes em vez de apenas contar arquivo faltando.
- [x] Adicionar filtro por projeto, tipo de asset e idade no cleanup de orfaos.
- [x] Exigir confirmacao explicita para cleanup destrutivo fora de dry-run.
- [x] Revisar politicas de custo padrao por provider/modelo.
- [x] Separar custo estimado, custo reportado pelo provider e custo final usado no budget.
- [x] Mostrar custo por etapa no workspace.
- [x] Emitir evento quando budget bloquear uma operacao.
- [x] Adicionar testes para `size_bytes` persistido.
- [x] Adicionar testes para reconciliacao de storage.
- [x] Adicionar testes para custo estimado vs custo real/reportado.

## Criterios de Aceite

- [x] Uso de storage abre rapido mesmo com muitos arquivos.
- [x] Cleanup de orfaos tem filtros e confirmacao segura.
- [x] Custos aparecem por etapa, provider e modelo.
- [x] Budget bloqueia operacoes caras com mensagem clara.

## Validacao Recomendada

- [x] `python -m pytest tests/test_storage_governance.py tests/test_costs.py -q`
- [x] `python -m pytest tests/test_video_retry.py tests/test_storyboard_timeline.py -q`
- [x] `ruff check .`
- [x] `mypy app tests`
- [x] `python -m pytest -q`
