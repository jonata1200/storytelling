# Fase 3: Planejamento de segmentos a partir do roteiro

## Objetivo

Transformar o roteiro em blocos de video revisaveis antes de gastar creditos com geracao.

## Entrada

- Roteiro aprovado.
- Cenas e planos, quando existirem.
- Biblioteca Visual aprovada.
- Preferencias de producao.
- Duracao alvo do video.

## Saida

Uma lista de segmentos com:

- Numero do segmento.
- Duracao.
- Acao principal.
- Personagens presentes.
- Local.
- Objetos importantes.
- Prompt de video.
- Prompt negativo.
- Continuidade esperada com segmento anterior.

## Checklist

- [x] Criar service para planejar segmentos continuos.
- [x] Dividir roteiro em blocos de duracao curta.
- [x] Gerar prompt por segmento em portugues.
- [x] Incluir referencias textuais da Biblioteca Visual.
- [x] Criar resumo visual de personagens, locais e objetos por segmento.
- [x] Evitar prompts genericos demais.
- [x] Criar validacao antes de gerar video.
- [x] Expor previsualizacao dos segmentos na UI.
- [x] Permitir editar prompt de segmento antes de gerar.
- [x] Criar testes para segmentacao de roteiro curto, medio e longo.

## Regras de prompt

- Preservar identidade, figurino, ambiente e escala definidos na Biblioteca Visual.
- Cada segmento deve ter uma acao principal clara.
- Segmentos seguintes devem continuar a acao anterior, nao reiniciar a cena.
- Evitar texto visual, logos, legendas e marcas d'agua.

## Resultado esperado

O usuario consegue revisar os blocos de video antes de iniciar a fila de geracao.
