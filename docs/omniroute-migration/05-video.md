# Fase 5 - Migração de geração de vídeos

Status: implementada em código e validada por testes automatizados. Smoke real fica
opcional, pois consome credenciais e pode gerar custo no provedor.

Objetivo: migrar text-to-video e image-to-video para OmniRoute/OmniRouters sem
perder controle de duração, aspect ratio, polling e download local.

## Checklist

- [x] Confirmar documentação final da Omni-Video API.
- [x] Confirmar endpoint de criação de vídeo.
- [x] Confirmar endpoint de status/polling.
- [x] Confirmar endpoint ou campo de download do vídeo final.
- [x] Confirmar campos equivalentes:
      `model`, `prompt`, `seconds`, `aspect_ratio`, `resolution`, `seed`.
- [x] Confirmar suporte a primeiro frame para image-to-video.
- [x] Confirmar suporte a múltiplas referências visuais.
- [x] Confirmar opções para desativar áudio nativo/BGM.
- [x] Criar `app/providers/video/omniroute.py`.
- [x] Manter áudio nativo desativado no payload do provider.
- [x] Mapear status OmniRoute para `GenerationJobStatus`.
- [x] Preservar validação de duração de vídeo.
- [x] Preservar download local para `storage_uri`.
- [x] Atualizar `_video_provider_for_project`.
- [x] Atualizar schemas/configuração para aceitar `provider="omniroute"`.
- [x] Atualizar custos/eventos para `omniroute_videos`.
- [x] Criar testes unitários para submit, polling, falha e download.
- [x] Criar smoke test manual com image-to-video vertical 9:16.

## Implementação

- Provider real: `app/providers/video/omniroute.py`.
- Seleção por configuração: `VIDEO_PROVIDER=omniroute` ou fallback via
  `AI_PROVIDER=omniroute`.
- Modelo preferencial: `OMNIROUTE_VIDEO_MODEL`.
- Chave: `OMNIROUTE_API_KEY`.
- Base URL: `OMNIROUTE_BASE_URL`, com padrão `https://omnirouters.com/v1`.
- Diretório lógico de custos/eventos: `omniroute_videos`.
- Áudio nativo permanece desativado por payload:
  `audio_generation`, `enable_bgm` e `keep_original_sound`.

## Testes

- [x] `tests/test_omniroute_video_speech.py` cobre criação do payload,
      image-to-video, primeiro frame, referências, polling, falha, download local
      e seleção do provider.
- [x] `tests/test_omniroute_video_speech_smoke.py` contém smoke real opcional.
- [x] `ruff`, `mypy` e `pytest` passam.
- [ ] Smoke real executado contra OmniRoute em ambiente com credencial e custo
      aprovado.

Para executar o smoke real:

```powershell
$env:OMNIROUTE_VIDEO_SMOKE="1"
$env:OMNIROUTE_API_KEY="..."
$env:OMNIROUTE_VIDEO_MODEL="Kling-3.0-omni"
.\.venv\Scripts\pytest.exe tests\test_omniroute_video_speech_smoke.py -k video
```

## Critérios de aceite

- [x] Um clipe image-to-video é submetido com primeiro frame preservado.
- [x] A duração do clipe respeita o plano.
- [x] O aspect ratio 9:16 é preservado.
- [x] O vídeo é baixado e salvo localmente.
- [x] O job falho aparece com erro claro para o usuário.
- [x] Testes de vídeo passam.
- [ ] Vídeo real validado visualmente após smoke com credenciais.
