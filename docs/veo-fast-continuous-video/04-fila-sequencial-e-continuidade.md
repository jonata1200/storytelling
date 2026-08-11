# Fase 4: Fila sequencial, retry e continuidade

## Objetivo

Implementar uma fila de geracao sequencial para video continuo, com capacidade de pausar, retomar e continuar a partir do ultimo segmento valido.

## Fluxo esperado

1. Gerar segmento 1 a partir de prompt e Biblioteca Visual.
2. Salvar asset e identificador externo do provider.
3. Gerar segmento 2 usando o segmento 1 como base de continuidade.
4. Repetir ate finalizar todos os segmentos.
5. Se houver falha, parar no segmento atual e permitir retry.

## Checklist

- [ ] Criar job type ou step especifico para video continuo.
- [ ] Garantir execucao sequencial por projeto.
- [ ] Criar submit/poll para Veo 3.1 Fast.
- [ ] Adicionar suporte a extensao de video quando disponivel.
- [ ] Salvar `external_operation_id` por segmento.
- [ ] Salvar asset de video por segmento concluido.
- [ ] Marcar segmento como `failed` com erro legivel.
- [ ] Permitir retry do segmento com falha.
- [ ] Permitir continuar a partir do ultimo segmento concluido.
- [ ] Evitar regerar segmentos concluidos.
- [ ] Detectar jobs `running` antigos e permitir retomada segura.
- [ ] Registrar eventos de observabilidade por segmento.
- [ ] Criar testes de fila sequencial.
- [ ] Criar testes de falha no segmento do meio.
- [ ] Criar testes de retomada sem duplicar custo de segmentos prontos.

## Regras de continuidade

- Segmento 1 nao depende de video anterior.
- Segmento N depende do segmento N-1 quando o modo for continuidade temporal.
- Se a API nao permitir extensao para um asset antigo, o app deve informar o usuario e oferecer regenerar a partir do ultimo ponto valido.

## Resultado esperado

O usuario consegue gerar video em blocos, parar, corrigir e continuar sem perder o que ja foi gerado.
