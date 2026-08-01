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

- [x] Criar `app/providers/speech/elevenlabs.py`.
- [x] Integrar ElevenLabs ao `speech_provider_from_settings`.
- [x] Mapear voz padrao e voz por personagem.
- [x] Salvar audio gerado no storage local.
- [x] Persistir alinhamento/duracao quando disponivel ou estimar quando nao houver retorno detalhado.
- [x] Criar `app/providers/dubbing/elevenlabs.py`.
- [x] Criar modulo `app/dubbing/`.
- [x] Criar tabela `dubbing_jobs`.
- [x] Criar migration Alembic.
- [x] Criar endpoint para iniciar dublagem de um export.
- [x] Criar polling/status de dublagem.
- [x] Criar download do resultado dublado.
- [x] Associar resultado ao export original.
- [x] Exibir estado da dublagem na configuracao/readiness e via endpoints de finalizacao.
- [x] Adicionar testes unitarios sem chamada real.
- [x] Adicionar smoke test real atras de flag explicita.

## Status de Implementacao

- Provider de voz criado com `POST /v1/text-to-speech/{voice_id}/with-timestamps`.
- Provider de dublagem criado com `POST /v1/dubbing`, `GET /v1/dubbing/{id}` e download por idioma.
- `dubbing_jobs` rastreia provider, idiomas, status, custo estimado, job externo e asset resultante.
- Endpoints de finalizacao iniciam, listam e atualizam dublagens de exports.
- A tela de Configuracoes de IA salva ElevenLabs, idioma original e idioma alvo.
- Smoke real deve ser habilitado explicitamente para evitar custo externo.

## Criterios de Aceite

- Audio de fala real e gerado via ElevenLabs.
- Export final pode iniciar dublagem.
- Resultado dublado fica associado ao projeto.
- A UI mostra pendente, processando, concluido e falhou.
