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

- [ ] Criar campos ou tabela para armazenar tamanho dos assets no momento da criacao.
- [ ] Atualizar criacao de imagens, video e audio para gravar `size_bytes`.
- [ ] Evitar depender de `rglob("*")` em consultas frequentes de uso.
- [ ] Manter varredura completa como acao administrativa sob demanda.
- [ ] Adicionar job de reconciliacao de storage local.
- [ ] Marcar assets ausentes em vez de apenas contar arquivo faltando.
- [ ] Adicionar filtro por projeto, tipo de asset e idade no cleanup de orfaos.
- [ ] Exigir confirmacao explicita para cleanup destrutivo fora de dry-run.
- [ ] Revisar politicas de custo padrao por provider/modelo.
- [ ] Separar custo estimado, custo reportado pelo provider e custo final usado no budget.
- [ ] Mostrar custo por etapa no workspace.
- [ ] Emitir evento quando budget bloquear uma operacao.
- [ ] Adicionar testes para `size_bytes` persistido.
- [ ] Adicionar testes para reconciliacao de storage.
- [ ] Adicionar testes para custo estimado vs custo real/reportado.

## Criterios de Aceite

- [ ] Uso de storage abre rapido mesmo com muitos arquivos.
- [ ] Cleanup de orfaos tem filtros e confirmacao segura.
- [ ] Custos aparecem por etapa, provider e modelo.
- [ ] Budget bloqueia operacoes caras com mensagem clara.

## Validacao Recomendada

- [ ] `python -m pytest tests/test_storage_governance.py tests/test_costs.py -q`
- [ ] `python -m pytest tests/test_video_retry.py tests/test_storyboard_timeline.py -q`
- [ ] `ruff check .`
- [ ] `mypy app tests`
- [ ] `python -m pytest -q`
