# Fase 06 - UI, Banco, Observabilidade e Testes

## Objetivo

Fechar a migracao com configuracao visivel, rastreabilidade, custos e testes.

## Resultado Esperado

O usuario deve conseguir configurar providers, executar a pipeline e entender
qual modelo gerou cada artefato.

## Checklist de UI

- [ ] Atualizar tela de configuracoes para Ollama Cloud.
- [ ] Atualizar tela de configuracoes para Google AI imagem.
- [ ] Atualizar tela de configuracoes para Google AI video.
- [ ] Atualizar tela de configuracoes para ElevenLabs voz/dublagem.
- [ ] Mostrar readiness por canal: texto, imagem, video, voz e dublagem.
- [ ] Mostrar erros de configuracao de forma acionavel.
- [ ] Adicionar acao "Dublar video" na finalizacao.
- [ ] Mostrar idioma de origem e destino na dublagem.

## Checklist de Banco e Storage

- [ ] Revisar se `ProjectProductionSettings` precisa de novos campos de modelo.
- [ ] Criar tabela `dubbing_jobs`.
- [ ] Persistir metadados de provider em cada asset gerado.
- [ ] Persistir custos estimados por provider/modelo.
- [ ] Garantir limpeza/reconciliacao de assets gerados.

## Checklist de Observabilidade

- [ ] Registrar eventos de submit, polling, sucesso e falha para Google AI image.
- [ ] Registrar eventos de submit, polling, sucesso e falha para Google AI video.
- [ ] Registrar eventos de submit, polling, sucesso e falha para ElevenLabs dubbing.
- [ ] Redigir chaves e URLs assinadas em logs.
- [ ] Incluir correlation id nos requests externos quando aplicavel.

## Checklist de Testes

- [ ] Testar settings e policy de providers.
- [ ] Testar provider Ollama Cloud com HTTP mockado.
- [ ] Testar provider Google AI image com HTTP mockado.
- [ ] Testar provider Google AI video com HTTP mockado.
- [ ] Testar provider ElevenLabs speech com HTTP mockado.
- [ ] Testar provider ElevenLabs dubbing com HTTP mockado.
- [ ] Testar fallback de texto.
- [ ] Testar erros de chave ausente.
- [ ] Testar erros de modelo ausente.
- [ ] Testar timeouts de polling.
- [ ] Testar criacao de dublagem a partir de export final.
- [ ] Manter smoke tests reais desabilitados por padrao.

## Criterios de Aceite

- A pipeline completa funciona com providers reais configurados.
- Sem provider real configurado, a UI explica exatamente o que falta.
- Testes unitarios rodam sem custo externo.
- Logs nao vazam segredos.
- Artefatos gerados mostram provider, modelo e metadados principais.
