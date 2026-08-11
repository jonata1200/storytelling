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

- [ ] Adicionar seletor de modo: Controle visual ou Video continuo economico.
- [ ] Ajustar navegacao para permitir pular Storyboard no modo continuo.
- [ ] Criar tela/lista de segmentos planejados.
- [ ] Criar edicao de prompt por segmento.
- [ ] Criar botao "Gerar proximo segmento".
- [ ] Criar botao "Gerar todos em sequencia".
- [ ] Criar botao "Continuar de onde parou".
- [ ] Criar popup de progresso com estados por segmento.
- [ ] Mostrar custo estimado antes de gerar.
- [ ] Mostrar custo restante durante a fila.
- [ ] Permitir pausar apos o segmento atual.
- [ ] Remover controles redundantes de consistencia visual.
- [ ] Mostrar mensagens simples de erro.
- [ ] Criar testes de view model.
- [ ] Criar testes dos handlers de UI.

## Estados do popup

- Pendente.
- Enviando.
- Processando.
- Concluido.
- Falhou.
- Pulado porque ja existe.

## Resultado esperado

O usuario entende o que esta sendo gerado, o que ja foi gerado e o que falta, sem precisar acompanhar logs tecnicos.
