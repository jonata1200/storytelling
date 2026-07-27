# Fase 7 - Finalizacao de Video e Provider de Voz

## Objetivo

Completar a etapa final do pipeline com voz real e renderizacao mais robusta.

## Escopo

- Implementar provider real de fala ou adaptar uma interface para multiplos providers.
- Gerar audio final com alinhamento para legendas.
- Melhorar exportacao FFmpeg para lidar com codecs/resolucoes diferentes.
- Adicionar normalizacao de clipes antes do concat final quando necessario.
- Permitir perfil de exportacao configuravel.
- Validar existencia e compatibilidade de assets antes de renderizar.

## Checklist de acoes

- [x] Definir interface de provider de fala.
- [x] Escolher primeiro provider real de voz.
- [x] Adicionar configuracoes de provider/modelo/voz.
- [x] Implementar chamada real de sintese de voz.
- [x] Persistir audio gerado como asset.
- [ ] Gerar alinhamento para legendas quando o provider suportar.
- [x] Criar fallback seguro quando alinhamento nao estiver disponivel.
- [x] Desbloquear fluxo de narracao final sem usar mock.
- [ ] Validar codecs, resolucao e fps dos clipes antes de exportar.
- [x] Implementar normalizacao FFmpeg quando clipes forem incompativeis.
- [x] Permitir perfil de exportacao configuravel.
- [x] Melhorar mensagens de erro de exportacao.
- [x] Adicionar testes para provider de voz.
- [ ] Adicionar testes para exportacao manifest-only.
- [ ] Adicionar testes para exportacao MP4 quando FFmpeg estiver disponivel.

## Implementado

- `app/providers/speech/openai_compatible.py` adiciona provider de fala real compativel
  com APIs no formato `/audio/speech`, configurado por `SPEECH_*`.
- `synthesize_narration` deixou de bloquear sempre por mock: agora chama o provider real,
  persiste `Asset` de audio, cria `AudioTrack` final, registra custo estimado e emite evento
  operacional.
- Quando o provider nao retorna alinhamento dedicado, o fluxo gera alinhamento por palavra a
  partir do transcript e da duracao estimada.
- Exportacao aceita perfil configuravel via payload (`fps`, `bitrate`, `resolution`,
  `video_codec`, `audio_codec`, `embed_subtitles`).
- FFmpeg tenta concat direto e, se falhar por incompatibilidade, reencoda clipes para o perfil
  final antes de concatenar.
- Erros de exportacao passam por redacao de segredos antes de entrar em `render_log`.

## Pendencias

- Adicionar suporte a alinhamento nativo quando o provider de fala escolhido retornar timestamps.
- Validar codecs/resolucao/fps com `ffprobe` antes da renderizacao, nao apenas por fallback.
- Cobrir manifest-only e MP4 real com testes condicionais a FFmpeg.

## Entregaveis

- Provider de voz real.
- Narracao final desbloqueada.
- Exportacao MP4 mais resiliente.
- Testes unitarios para montagem e fallback de manifest.

## Criterios de aceite

- Pipeline consegue gerar narracao final sem provider mock.
- Exportacao falha com mensagem clara quando assets sao incompativeis.
- Quando FFmpeg esta disponivel e assets sao validos, exporta MP4 final.
