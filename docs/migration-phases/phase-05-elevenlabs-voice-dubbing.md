# Fase 05 - Voz e Dublagem com ElevenLabs

## Objetivo

Usar ElevenLabs para vozes dos personagens e adicionar dublagem como etapa final
do fluxo de exportacao.

## Resultado Esperado

A aplicacao deve conseguir:

- Gerar audio de dialogo/narracao por personagem.
- Exportar o video final.
- Enviar o export para dublagem em outro idioma.
- Baixar e registrar o video/audio dublado como novo asset.

## Variaveis Propostas

```env
SPEECH_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
ELEVENLABS_SPEECH_MODEL=...

DUBBING_PROVIDER=elevenlabs
DUBBING_SOURCE_LANG=pt
DUBBING_TARGET_LANG=en
DUBBING_POLL_INTERVAL_SECONDS=10
DUBBING_POLL_TIMEOUT_SECONDS=900
```

## Checklist

- [ ] Criar `app/providers/speech/elevenlabs.py`.
- [ ] Integrar ElevenLabs ao `speech_provider_from_settings`.
- [ ] Mapear voz padrao e voz por personagem.
- [ ] Salvar audio gerado no storage local.
- [ ] Persistir alinhamento/duracao quando disponivel ou estimar quando nao houver retorno detalhado.
- [ ] Criar `app/providers/dubbing/elevenlabs.py`.
- [ ] Criar modulo `app/dubbing/`.
- [ ] Criar tabela `dubbing_jobs`.
- [ ] Criar migration Alembic.
- [ ] Criar endpoint para iniciar dublagem de um export.
- [ ] Criar polling/status de dublagem.
- [ ] Criar download do resultado dublado.
- [ ] Associar resultado ao export original.
- [ ] Exibir estado da dublagem na UI de finalizacao.
- [ ] Adicionar testes unitarios sem chamada real.
- [ ] Adicionar smoke test real atras de flag explicita.

## Criterios de Aceite

- Audio de fala real e gerado via ElevenLabs.
- Export final pode iniciar dublagem.
- Resultado dublado fica associado ao projeto.
- A UI mostra pendente, processando, concluido e falhou.
