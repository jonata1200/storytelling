# Fase 05 - Polimento de UI e Acessibilidade

## Objetivo

Garantir que a experiencia de busca/filtros seja clara, responsiva e confortavel
em telas pequenas e grandes.

## Escopo

- Layout das barras de busca.
- Icones, tooltips e estados visuais.
- Responsividade mobile.
- Feedback visual de filtros ativos.

## Checklist de Implementacao

- [x] Usar icone de busca no campo principal.
- [x] Usar selects compactos para filtros.
- [x] Usar botao com icone para limpar filtros.
- [x] Adicionar tooltip no botao de limpar filtros.
- [x] Mostrar chips ou badges de filtros ativos quando fizer sentido.
- [x] Garantir que labels nao quebrem ou sobreponham em mobile.
- [x] Garantir que campos ocupem largura adequada em desktop.
- [x] Evitar cards dentro de cards nas areas de filtro.
- [x] Manter visual coerente com a paleta e componentes existentes.
- [x] Validar estado vazio com mensagem curta e acao clara.
- [x] Conferir navegacao por teclado nos campos.
- [x] Conferir contraste dos textos e placeholders.

## Criterios de Aceite

- [x] Busca e filtros ficam visiveis sem competir com a acao principal.
- [x] Mobile nao tem sobreposicao de texto ou controles.
- [x] O usuario entende quando ha filtros ativos.
- [x] O usuario consegue limpar filtros facilmente.

## Validacao Recomendada

- [ ] Verificar visualmente `/projects` em desktop e mobile.
- [ ] Verificar visualmente `/ideas` em desktop e mobile.
- [ ] Testar busca digitando rapidamente.
- [x] `ruff check app tests`
