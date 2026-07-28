# Fase 6 - Speech e vozes por personagem

Objetivo: avaliar se as vozes consistentes por personagem devem continuar no
provider OpenAI-compatible atual ou migrar para OmniRoute.

## Checklist

- [ ] Confirmar se OmniRoute oferece endpoint de speech compatível com OpenAI.
- [ ] Confirmar URL, modelos, vozes disponíveis e formato de resposta.
- [ ] Confirmar se `voice_profile_id` pode mapear para vozes estáveis.
- [ ] Confirmar se há clonagem de voz ou apenas vozes pré-definidas.
- [ ] Confirmar limites de tamanho de texto por requisição.
- [ ] Confirmar formato de áudio retornado: WAV, MP3, base64 ou stream.
- [ ] Decidir se `SPEECH_PROVIDER` aceitará `omniroute`.
- [ ] Criar `app/providers/speech/omniroute.py`, se necessário.
- [ ] Preservar a regra de uma voz estável por personagem.
- [ ] Preservar `dialogue_only`, sem narração.
- [ ] Atualizar readiness de `character_speech`.
- [ ] Criar testes de mapeamento de voz e síntese mockada.
- [ ] Criar smoke test manual com dois personagens falando no mesmo projeto.

## Critérios de aceite

- [ ] Cada personagem mantém a mesma voz entre frames diferentes.
- [ ] Fala de personagem desconhecido recebe fallback estável.
- [ ] Não há narração gerada.
- [ ] Export final mistura as vozes no MP4.
- [ ] Readiness mostra configuração correta de speech.

