# Fase 5: Interface da etapa de video continuo

## Objetivo

Criar uma experiencia clara para revisar, gerar e acompanhar video continuo, mantendo o padrao de popup de progresso ja usado nas outras etapas.

## Mudancas de UX

- Adicionar escolha de modo de producao no projeto.
- No modo continuo, a etapa de Storyboard nao deve ser obrigatoria.
- A etapa de Video deve mostrar segmentos planejados.
- A geracao so inicia por comando explicito.
- O progresso deve aparecer em popup.

## Checklist

- [x] Adicionar seletor de modo: Controle visual ou Video continuo economico.
- [x] Ajustar navegacao para permitir pular Storyboard no modo continuo.
- [x] Criar tela/lista de segmentos planejados.
- [x] Criar edicao de prompt por segmento.
- [x] Criar botao "Gerar proximo segmento".
- [x] Criar botao "Gerar todos em sequencia".
- [x] Criar botao "Continuar de onde parou".
- [x] Criar popup de progresso com estados por segmento.
- [x] Mostrar custo estimado antes de gerar.
- [x] Mostrar custo restante durante a fila.
- [x] Permitir pausar apos o segmento atual.
- [x] Remover controles redundantes de consistencia visual.
- [x] Mostrar mensagens simples de erro.
- [x] Criar testes de view model.
- [x] Criar testes dos handlers de UI.

## Estados do popup

- Pendente.
- Enviando.
- Processando.
- Concluido.
- Falhou.
- Pulado porque ja existe.

## Resultado esperado

O usuario entende o que esta sendo gerado, o que ja foi gerado e o que falta, sem precisar acompanhar logs tecnicos.
