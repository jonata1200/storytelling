# Fase 6 - Speech e vozes por personagem

Status: implementada em código e validada por testes automatizados. Smoke real fica
opcional, pois depende de modelo/vozes disponíveis na conta OmniRoute.

Objetivo: permitir speech via OmniRoute sem perder a regra principal da aplicação:
vídeo final em modo `dialogue_only`, sem narração, com voz estável por personagem.

## Checklist

- [x] Confirmar que a API é OpenAI-compatible e usa autenticação Bearer.
- [x] Confirmar base URL e rota compatível para speech.
- [x] Manter `voice_profile_id` como mapeamento de vozes estáveis.
- [x] Registrar que clonagem de voz não foi habilitada nesta fase.
- [x] Confirmar formato retornado pelo provider implementado: WAV.
- [x] Decidir que `SPEECH_PROVIDER` aceita `omniroute`.
- [x] Criar `app/providers/speech/omniroute.py`.
- [x] Preservar a regra de uma voz estável por personagem.
- [x] Preservar `dialogue_only`, sem narração.
- [x] Atualizar readiness de `character_speech`.
- [x] Criar testes de mapeamento de voz e síntese mockada.
- [x] Criar smoke test manual com duas vozes de personagem.
- [ ] Confirmar catálogo final de modelos e vozes disponíveis na conta usada em
      produção.
- [ ] Confirmar limites reais de tamanho de texto por requisição no modelo
      escolhido.

## Implementação

- Provider real: `app/providers/speech/omniroute.py`.
- Seleção por configuração: `SPEECH_PROVIDER=omniroute`.
- Modelo preferencial: `OMNIROUTE_SPEECH_MODEL`.
- Fallback de modelo: `SPEECH_MODEL`.
- Chave: `OMNIROUTE_API_KEY`.
- Base URL: `OMNIROUTE_BASE_URL`, com padrão `https://omnirouters.com/v1`.
- Rota utilizada: `/audio/speech`.
- O payload usa `voice_profile_id` como `voice`, preservando a voz estável
  calculada por personagem.

## Vozes por personagem

- [x] O fluxo de finalização continua calculando uma voz fixa por personagem.
- [x] A voz é salva no perfil narrativo do personagem quando necessário.
- [x] Personagens desconhecidos recebem fallback estável.
- [x] A geração de áudio usa apenas falas de diálogo.
- [x] O export continua marcando `audio_mode` como `dialogue_only`.

## Testes

- [x] `tests/test_omniroute_video_speech.py` cobre seleção do provider,
      readiness, escolha de modelo e preservação de `voice_profile_id`.
- [x] `tests/test_omniroute_video_speech_smoke.py` contém smoke real opcional
      para duas vozes de personagem.
- [x] `ruff`, `mypy` e `pytest` passam.
- [ ] Smoke real executado contra OmniRoute em ambiente com credencial, modelo e
      vozes aprovados.

Para executar o smoke real:

```powershell
$env:OMNIROUTE_SPEECH_SMOKE="1"
$env:OMNIROUTE_API_KEY="..."
$env:OMNIROUTE_SPEECH_MODEL="..."
$env:OMNIROUTE_SPEECH_VOICE_A="..."
$env:OMNIROUTE_SPEECH_VOICE_B="..."
.\.venv\Scripts\pytest.exe tests\test_omniroute_video_speech_smoke.py -k speech
```

## Critérios de aceite

- [x] Cada personagem mantém a mesma voz entre frames diferentes.
- [x] Fala de personagem desconhecido recebe fallback estável.
- [x] Não há narração gerada.
- [x] Export final mistura as vozes no MP4 pelo fluxo existente.
- [x] Readiness mostra configuração correta de speech.
- [ ] Vozes reais validadas auditivamente após smoke com credenciais.
