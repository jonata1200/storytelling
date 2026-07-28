# Fase 5 - Migração de geração de vídeos

Objetivo: migrar text-to-video e image-to-video para OmniRoute/OmniRouters sem
perder controle de duração, aspect ratio, polling e download local.

## Checklist

- [ ] Confirmar documentação final da Omni-Video API.
- [ ] Confirmar endpoint de criação de vídeo.
- [ ] Confirmar endpoint de status/polling.
- [ ] Confirmar endpoint ou campo de download do vídeo final.
- [ ] Confirmar campos equivalentes:
      `model`, `prompt`, `duration`, `aspect_ratio`, `resolution`, `seed`.
- [ ] Confirmar suporte a primeiro frame para image-to-video.
- [ ] Confirmar suporte a múltiplas referências visuais.
- [ ] Confirmar se há opção para desativar áudio nativo.
- [ ] Criar `app/providers/video/omniroute.py`.
- [ ] Manter `generate_audio=False` ou equivalente.
- [ ] Mapear status OmniRoute para `GenerationJobStatus`.
- [ ] Preservar validação de duração de vídeo.
- [ ] Preservar download local para `storage_uri`.
- [ ] Atualizar `_video_provider_for_project`.
- [ ] Atualizar schemas para aceitar `provider="omniroute"`.
- [ ] Atualizar custos/eventos para `omniroute_videos`.
- [ ] Criar testes unitários para submit, polling, falha e download.
- [ ] Criar smoke test manual com image-to-video vertical 9:16.

## Pontos de atenção

- Esta é a fase de maior risco.
- O app depende de image-to-video para preservar o primeiro frame do storyboard.
- O provider atual desativa áudio nativo para evitar narração. Isso precisa ser
  preservado.
- Só fazer corte final depois de validar vídeos reais.

## Critérios de aceite

- [ ] Um clipe image-to-video é gerado com primeiro frame preservado.
- [ ] A duração do clipe respeita o plano.
- [ ] O aspect ratio 9:16 é preservado.
- [ ] O vídeo é baixado e salvo localmente.
- [ ] O job falho aparece com erro claro para o usuário.
- [ ] Testes de vídeo passam.

