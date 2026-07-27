# Fase 6 - Custos, Orcamentos e Limites de Uso

## Objetivo

Dar previsibilidade ao uso de OpenRouter e evitar gastos acidentais.

## Escopo

- Modelar custo estimado por provider/modelo/operacao.
- Definir orcamento por projeto e por etapa.
- Exibir estimativa antes de gerar lotes de imagem/video.
- Bloquear ou exigir confirmacao quando passar do limite.
- Registrar custo real retornado pelo provider e comparar com estimativa.
- Melhorar observabilidade de custo acumulado por projeto.

## Checklist de acoes

- [ ] Mapear operacoes pagas atuais: texto, imagem e video.
- [ ] Definir tabela/configuracao de custo por provider, modelo e operacao.
- [ ] Criar estimador de custo para texto.
- [ ] Criar estimador de custo para imagem.
- [ ] Criar estimador de custo para video.
- [ ] Definir orcamento por projeto.
- [ ] Definir limite opcional por etapa.
- [ ] Exibir estimativa antes de gerar storyboards em lote.
- [ ] Exibir estimativa antes de gerar videos em lote.
- [ ] Exigir confirmacao quando estimativa passar do limite.
- [ ] Registrar custo real retornado pelo provider.
- [ ] Comparar custo estimado versus custo real.
- [ ] Criar resumo por projeto, etapa, provider e modelo.
- [ ] Adicionar testes de limite e bloqueio.

## Entregaveis

- Politica de orcamento por projeto.
- Estimativa antes de chamadas caras.
- Registro de custo estimado versus real.
- Alertas de limite atingido.

## Criterios de aceite

- Usuario ve custo estimado antes de gerar video em lote.
- Operacoes caras respeitam limite configurado.
- Relatorio de custos mostra total por etapa, provider e modelo.
