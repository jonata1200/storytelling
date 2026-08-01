# Fase 06 - UI, Banco, Observabilidade e Testes

## Objetivo

Fechar a migracao com configuracao visivel, rastreabilidade, custos e testes.

## Resultado Esperado

O usuario deve conseguir configurar providers, executar a pipeline e entender
qual modelo gerou cada artefato.

## Checklist de UI

- [x] Atualizar tela de configuracoes para Ollama Cloud.
- [x] Atualizar tela de configuracoes para Google AI imagem.
- [x] Atualizar tela de configuracoes para Google AI video.
- [x] Atualizar tela de configuracoes para ElevenLabs voz/dublagem.
- [x] Mostrar readiness por canal: texto, imagem, video, voz e dublagem.
- [x] Mostrar erros de configuracao de forma acionavel.
- [x] Adicionar acao "Dublar video" via endpoint de finalizacao.
- [x] Mostrar idioma de origem e destino na dublagem via configuracao/readiness e payloads.

## Checklist de Banco e Storage

- [x] Revisar se `ProjectProductionSettings` precisa de novos campos de modelo.
- [x] Criar tabela `dubbing_jobs`.
- [x] Persistir metadados de provider em cada asset gerado.
- [x] Persistir custos estimados por provider/modelo.
- [x] Garantir limpeza/reconciliacao de assets gerados.

## Checklist de Observabilidade

- [x] Registrar eventos de submit, polling, sucesso e falha para Google AI image.
- [x] Registrar eventos de submit, polling, sucesso e falha para Google AI video.
- [x] Registrar eventos de submit, polling, sucesso e falha para ElevenLabs dubbing.
- [x] Redigir chaves e URLs assinadas em logs.
- [x] Incluir correlation id nos requests externos quando aplicavel.

## Checklist de Testes

- [x] Testar settings e policy de providers.
- [x] Testar provider Ollama Cloud com HTTP mockado.
- [x] Testar provider Google AI image com HTTP mockado.
- [x] Testar provider Google AI video com HTTP mockado.
- [x] Testar provider ElevenLabs speech com HTTP mockado.
- [x] Testar provider ElevenLabs dubbing com HTTP mockado.
- [x] Testar fallback de texto.
- [x] Testar erros de chave ausente.
- [x] Testar erros de modelo ausente.
- [x] Testar timeouts de polling.
- [x] Testar criacao de dublagem a partir de export final.
- [x] Manter smoke tests reais desabilitados por padrao.

## Status de Implementacao

- Configuracoes visiveis para texto, imagem, video, voz e dublagem.
- Readiness inclui `character_speech` e `dubbing`.
- Banco recebe `dubbing_jobs` e limpeza de projetos remove esses registros.
- Testes unitarios cobrem providers novos e fluxo de dublagem sem custo externo.

## Criterios de Aceite

- A pipeline completa funciona com providers reais configurados.
- Sem provider real configurado, a UI explica exatamente o que falta.
- Testes unitarios rodam sem custo externo.
- Logs nao vazam segredos.
- Artefatos gerados mostram provider, modelo e metadados principais.
