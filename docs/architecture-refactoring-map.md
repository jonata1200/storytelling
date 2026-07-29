# Mapa de Refatoracao

## Workspace Storyboard/Video

- `app/ui/workspace/storyboard_video_area.py`: renderizacao das abas Storyboard e Video.
- `app/ui/workspace/storyboard_handlers.py`: handlers de aprovacao, edicao e geracao de storyboard.
- `app/ui/workspace/video_handlers.py`: handlers de prompt de video.
- `app/ui/workspace/storyboard_video_view_model.py`: preparacao de dados para renderizacao.

## Video Generation

- `app/video_generation/service.py`: orquestracao publica e persistencia do dominio de clips.
- Preparacao de jobs, execucao do provider e persistencia foram isoladas em helpers internos
  com contratos pequenos para reduzir regressao.
- `app/providers/video/omniroute.py`: fronteira provider com submit, polling e download separados.

## Finalization

- `app/finalization/service.py`: ainda concentra timeline, audio, FFmpeg e manifest.
- `app/finalization/subtitles.py`: regras de legenda e safe area.
- Proximo passo recomendado: extrair `timeline_builder.py`, `audio_mix.py`, `ffmpeg_exporter.py`
  e `export_manifest.py`.

## Project Agent

- `app/generation/project_agent.py`: orquestracao de alto nivel.
- Pipelines auxiliares ja estao separados em `project_agent_context.py`,
  `project_agent_intent.py`, `project_agent_routing.py`, `project_agent_support.py`,
  `project_agent_types.py` e `project_agent_visual.py`.
- Proximo passo recomendado: mover `_ensure_script_pipeline`, `_ensure_storyboard_pipeline`,
  `_ensure_video_pipeline`, `_ensure_finalization_pipeline` e `_ensure_quality_pipeline`
  para modulos dedicados quando houver alteracao funcional nesses fluxos.

## Helpers Compartilhados

- Criacao de artefatos e dependencias ainda aparece em alguns dominios por compatibilidade.
- Proximo passo recomendado: consolidar em um servico `app/workflows/artifacts.py` quando
  as proximas fases mexerem em versionamento ou invalidacao.
