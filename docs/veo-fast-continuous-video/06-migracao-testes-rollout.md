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

- [ ] Criar migration sem perda de dados.
- [ ] Adicionar defaults seguros para projetos antigos.
- [ ] Atualizar resumo do projeto para incluir modo de producao.
- [ ] Atualizar permissao de acesso entre etapas.
- [ ] Atualizar agente para entender o novo modo.
- [ ] Atualizar textos de UI para o modo continuo.
- [ ] Criar smoke test com provider mock.
- [ ] Criar teste de custo estimado.
- [ ] Criar teste de geracao parcial.
- [ ] Criar teste de retomada apos falha.
- [ ] Criar teste de projeto antigo com Storyboards.
- [ ] Criar teste de projeto novo em modo continuo.
- [ ] Documentar limitacoes conhecidas.
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
