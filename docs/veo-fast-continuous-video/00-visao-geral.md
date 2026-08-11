# Plano: Video continuo economico com Google Veo 3.1 Fast

## Objetivo

Adicionar um modo de producao mais barato e continuo para a etapa de video, usando Google Veo 3.1 Fast, geracao em blocos e continuidade temporal entre segmentos.

O fluxo atual com Storyboards deve continuar existindo para projetos que precisam de controle visual fino. O novo fluxo deve ser uma opcao de producao, nao uma substituicao imediata.

## Fluxos suportados

1. Controle visual: Biblioteca Visual -> Storyboards -> Videos.
2. Video continuo economico: Biblioteca Visual -> Segmentos de video -> Video final.
3. Hibrido futuro: Biblioteca Visual -> Keyframes selecionados -> Segmentos de video.

## Principios

- O usuario so inicia geracao de video por comando explicito, via botao ou agente.
- A Biblioteca Visual e sempre a base de consistencia visual.
- O modo continuo usa fila sequencial, pois cada segmento pode depender do anterior.
- Falhas nao devem obrigar regerar segmentos ja concluidos.
- A interface deve usar popup de progresso, seguindo o padrao das outras etapas.
- O sistema deve manter estimativa de custo clara antes de enviar jobs ao provider.

## Referencias tecnicas

- Google Veo API: https://ai.google.dev/gemini-api/docs/video
- Google Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing

## Fases

- Fase 1: Configuracao de provider, modelo e custo.
- Fase 2: Modelo de dados para segmentos continuos.
- Fase 3: Planejamento de segmentos a partir do roteiro.
- Fase 4: Fila sequencial, retry e continuidade.
- Fase 5: Interface da etapa de video continuo.
- Fase 6: Migracao, testes e rollout.

## Criterios finais de sucesso

- O usuario consegue criar video continuo sem gerar Storyboards.
- O usuario consegue gerar apenas um segmento e continuar depois.
- O app consegue continuar a partir do ultimo segmento valido apos falha.
- O custo estimado aparece antes da geracao.
- O fluxo atual com Storyboards permanece funcional.
- A geracao de video nunca comeca apenas por entrar na etapa.
