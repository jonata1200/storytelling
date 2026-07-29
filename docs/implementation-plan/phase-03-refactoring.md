# Fase 03 - Refatoracao de Modulos Grandes

## Objetivo

Reduzir risco de regressao e facilitar manutencao extraindo responsabilidades
dos maiores modulos de UI, finalizacao, video e agente do projeto.

## Escopo

- Separacao de renderizacao, handlers de UI e regras de dominio.
- View models para telas complexas.
- Servicos menores para video/finalizacao/storyboard.
- Reducao de imports indiretos por fachada.

## Checklist de Implementacao

- [ ] Mapear responsabilidades de `storyboard_video_area.py`.
- [ ] Extrair handlers de storyboard para modulo proprio.
- [ ] Extrair handlers de video prompt/clip para modulo proprio.
- [ ] Criar view model para a aba Storyboard/Video.
- [ ] Mapear responsabilidades de `finalization/service.py`.
- [ ] Separar montagem de timeline, audio, FFmpeg e export manifest.
- [ ] Mapear responsabilidades de `video_generation/service.py`.
- [ ] Separar preparacao de jobs, execucao do provider e persistencia de resultado.
- [ ] Mapear responsabilidades de `project_agent.py`.
- [ ] Separar pipelines de script, visual, storyboard, video, finalizacao e qualidade.
- [ ] Reduzir uso de imports reexportados com `# noqa: F401` onde for possivel.
- [ ] Padronizar helpers de `create_artifact` e `add_dependency` entre dominios.
- [ ] Criar testes antes de mover blocos com comportamento critico.
- [ ] Mover codigo em passos pequenos, mantendo testes verdes apos cada extracao.
- [ ] Atualizar documentacao de arquitetura com o novo mapa de modulos.

## Criterios de Aceite

- [ ] Nenhum arquivo de UI/orquestracao critica concentra responsabilidades demais.
- [ ] Renderizadores nao executam regra de dominio pesada diretamente.
- [ ] Handlers de UI sao testaveis sem montar a pagina completa.
- [ ] Testes, lint e mypy passam.

## Validacao Recomendada

- [ ] `python -m pytest tests/test_project_creation_ui.py tests/test_project_creation_workspace.py -q`
- [ ] `python -m pytest tests/test_project_agent_script.py tests/test_project_agent_storyboard_video.py -q`
- [ ] `ruff check .`
- [ ] `mypy app tests`
- [ ] `python -m pytest -q`
