# Fase 1: Provider, modelo e custos

## Objetivo

Preparar a aplicacao para usar Google Veo 3.1 Fast como modelo padrao do modo de video continuo economico, sem quebrar o fluxo atual de video por storyboard.

## Decisoes esperadas

- Modelo do modo continuo: `veo-3.1-fast-generate-preview`.
- Resolucao padrao: `720p`.
- Duracao por bloco: preferencialmente 7s quando o fluxo usar extensao.
- O modelo Standard pode continuar disponivel para fluxo de maior qualidade.
- O Lite nao deve ser usado no fluxo principal de video da aplicacao.

## Checklist

- [x] Adicionar `veo-3.1-fast-generate-preview` na lista de modelos aceitos.
- [x] Criar configuracao separada para modelo de video continuo.
- [x] Manter `veo-3.1-generate-preview` para fluxo atual, se necessario.
- [x] Atualizar `.env.example` com a nova variavel de modelo continuo.
- [x] Atualizar tela de configuracoes para exibir o modelo do modo continuo.
- [x] Atualizar estimativa de custo para diferenciar Standard e Fast.
- [x] Criar testes para normalizacao de modelo Fast.
- [x] Criar testes para estimativa de custo do modo continuo.
- [x] Garantir que configuracoes antigas com modelo removido caiam em default valido.

## Pontos de atencao

- Confirmar o nome exato do modelo na conta/API antes de usar em producao.
- Preco confirmado no momento da implementacao: Veo 3.1 Fast em 720p custa US$ 0,10/s no nivel pago da Gemini API.
- Nao misturar parametros nao suportados pelo provider, como ocorreu com `inlineData` e `numberOfVideos`.

## Resultado esperado

O sistema reconhece Google Veo 3.1 Fast como opcao oficial do modo continuo e calcula custo com base no modelo escolhido.
