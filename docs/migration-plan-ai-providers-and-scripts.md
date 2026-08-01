# Plano de Migracao por Fases

Este plano organiza a migracao dos providers de IA e a simplificacao dos scripts
locais em fases independentes. Cada fase tem seu proprio arquivo e checklist de
acoes.

## Decisoes Atuais

- Texto: Ollama Cloud.
- Imagem: Google AI / Gemini API com modelos Nano Banana.
- Video: Google AI / Gemini API com Gemini Omni Flash e/ou Veo.
- Voz e dublagem final: ElevenLabs.
- Scripts locais: reduzir o uso diario para 3 comandos.

## Fases

1. [Fase 01 - Scripts locais simplificados](migration-phases/phase-01-scripts.md)
2. [Fase 02 - Texto com Ollama Cloud](migration-phases/phase-02-ollama-cloud-text.md)
3. [Fase 03 - Imagens com Google AI](migration-phases/phase-03-google-ai-images.md)
4. [Fase 04 - Videos com Google AI](migration-phases/phase-04-google-ai-video.md)
5. [Fase 05 - Voz e dublagem com ElevenLabs](migration-phases/phase-05-elevenlabs-voice-dubbing.md)
6. [Fase 06 - UI, banco, observabilidade e testes](migration-phases/phase-06-productization-and-tests.md)

## Fontes Oficiais

- Ollama Cloud: https://docs.ollama.com/cloud
- Ollama API: https://docs.ollama.com/api
- Google AI image generation: https://ai.google.dev/gemini-api/docs/image-generation
- Google AI video generation: https://ai.google.dev/gemini-api/docs/video
- Google AI Veo guide: https://ai.google.dev/gemini-api/docs/veo
- Google AI models: https://ai.google.dev/gemini-api/docs/models
- ElevenLabs Dubbing API: https://elevenlabs.io/docs/api-reference/dubbing/create

## Observacoes Importantes

- As docs atuais do Google AI recomendam Nano Banana para imagens. Imagen esta
  marcado como deprecated e com desligamento previsto para 17 de agosto de 2026,
  portanto nao deve ser usado como base de migracao.
- Para video, as docs atuais do Gemini API listam Gemini Omni Flash e Veo como
  caminhos oficiais de geracao. O plano separa imagem e video em fases distintas
  porque os contratos, latencia, custos e polling sao diferentes.
- Testes automatizados nao devem chamar APIs pagas por padrao. Chamadas reais
  devem ficar atras de flags explicitas de smoke test.
