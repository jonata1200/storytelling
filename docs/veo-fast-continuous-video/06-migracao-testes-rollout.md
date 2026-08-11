# Fase 6: Migracao, testes e rollout

## Objetivo

Entregar o modo de video continuo com seguranca, sem quebrar projetos existentes e sem remover o fluxo de Storyboards antes de validacao real.

## Estrategia de migracao

- Projetos existentes mantem o modo atual.
- Projetos novos podem escolher o modo no inicio.
- A troca de modo em projeto existente deve ser explicita.
- Se um projeto ja tiver Storyboards, eles continuam preservados.
- Se um projeto estiver em modo continuo, Storyboards viram etapa opcional.

## Checklist

- [x] Criar migration sem perda de dados.
- [x] Adicionar defaults seguros para projetos antigos.
- [x] Atualizar resumo do projeto para incluir modo de producao.
- [x] Atualizar permissao de acesso entre etapas.
- [x] Atualizar agente para entender o novo modo.
- [x] Atualizar textos de UI para o modo continuo.
- [x] Criar smoke test com provider mock.
- [x] Criar teste de custo estimado.
- [x] Criar teste de geracao parcial.
- [x] Criar teste de retomada apos falha.
- [x] Criar teste de projeto antigo com Storyboards.
- [x] Criar teste de projeto novo em modo continuo.
- [x] Documentar limitacoes conhecidas.
- [ ] Validar com um projeto pequeno antes de liberar para projetos longos.

## Validacao manual recomendada

1. Criar projeto novo em modo continuo.
2. Gerar Biblioteca Visual.
3. Planejar 3 segmentos.
4. Gerar apenas o primeiro segmento.
5. Sair e voltar ao projeto.
6. Continuar do segundo segmento.
7. Forcar falha no segundo segmento com provider mock.
8. Corrigir prompt e retentar apenas o segundo.
9. Confirmar que o primeiro nao foi regerado.
10. Gerar video final a partir dos segmentos.

## Resultado esperado

O modo continuo fica disponivel como beta confiavel, com rollback simples para o fluxo atual de Storyboards.

## Limitacoes conhecidas

- O modo continuo ainda deve ser tratado como beta ate passar pela validacao manual com um projeto pequeno usando a chave real do provider.
- A continuidade entre segmentos usa o ultimo segmento aprovado como referencia operacional, mas o provider Google AI atual nao expoe extensao real de video nesta integracao; quando nao houver suporte de extensao, a continuidade cai para prompt continuity.
- A montagem/exportacao final a partir de segmentos continuos ainda precisa ser validada no fluxo de finalizacao antes de substituir o fluxo classico de Storyboards em projetos longos.
- Projetos antigos permanecem no modo classico por default. A troca para video continuo deve ser feita de forma explicita na UI ou nas configuracoes de producao.
