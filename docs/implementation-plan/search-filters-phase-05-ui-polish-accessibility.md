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

- [ ] Usar icone de busca no campo principal.
- [ ] Usar selects compactos para filtros.
- [ ] Usar botao com icone para limpar filtros.
- [ ] Adicionar tooltip no botao de limpar filtros.
- [ ] Mostrar chips ou badges de filtros ativos quando fizer sentido.
- [ ] Garantir que labels nao quebrem ou sobreponham em mobile.
- [ ] Garantir que campos ocupem largura adequada em desktop.
- [ ] Evitar cards dentro de cards nas areas de filtro.
- [ ] Manter visual coerente com a paleta e componentes existentes.
- [ ] Validar estado vazio com mensagem curta e acao clara.
- [ ] Conferir navegacao por teclado nos campos.
- [ ] Conferir contraste dos textos e placeholders.

## Criterios de Aceite

- [ ] Busca e filtros ficam visiveis sem competir com a acao principal.
- [ ] Mobile nao tem sobreposicao de texto ou controles.
- [ ] O usuario entende quando ha filtros ativos.
- [ ] O usuario consegue limpar filtros facilmente.

## Validacao Recomendada

- [ ] Verificar visualmente `/projects` em desktop e mobile.
- [ ] Verificar visualmente `/ideas` em desktop e mobile.
- [ ] Testar busca digitando rapidamente.
- [ ] `ruff check app tests`
