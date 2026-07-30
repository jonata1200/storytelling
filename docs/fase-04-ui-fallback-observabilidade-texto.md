# Fase 04 - UI, Fallback E Observabilidade De Texto

## Objetivo

Permitir que o usuario escolha provider/modelo de texto na interface, configure
chaves e veja claramente qual provider falhou ou foi usado.

## Comportamento Esperado

- A tela de Configuracoes de IA deve mostrar providers de texto.
- Cada provider deve exibir base URL, chave e modelo.
- O usuario deve poder salvar chaves pela UI local.
- A aplicacao deve mostrar readiness por provider.
- Fallback deve ser explicito e observavel.

## Checklist UI

- [ ] Criar seletor `Provider de texto`: Ollama, Groq, NVIDIA NIM.
- [ ] Mostrar campos especificos do provider selecionado.
- [ ] Permitir salvar chaves de Groq e NVIDIA NIM pela UI.
- [ ] Permitir editar base URL de Ollama e NVIDIA NIM.
- [ ] Mostrar lista selecionavel de modelos por provider.
- [ ] Se um modelo salvo nao estiver na lista, inclui-lo como opcao adicional.
- [ ] Remover textos e campos OmniRoute.
- [ ] Atualizar copy da pagina para explicar fallback.

## Checklist Fallback

- [ ] Adicionar `TEXT_PROVIDER_FALLBACKS`.
- [ ] Implementar fallback opcional em `llm_provider_for_task`.
- [ ] Registrar provider primario e provider final usado.
- [ ] Nao fazer fallback quando erro for validacao de prompt/JSON recuperavel.
- [ ] Fazer fallback em timeout, 429, 5xx e erro de rede.
- [ ] Nao fazer fallback em erro de chave ausente sem notificar claramente.

## Checklist Observabilidade

- [ ] Atualizar readiness para listar `text_provider`.
- [ ] Incluir detalhes: provider, base_url, model, api_key_configured.
- [ ] Registrar falhas por provider em `OperationalEvent`.
- [ ] Registrar fallback em `PromptExecution.parameters`.
- [ ] Redigir chaves em logs e eventos.

## Checklist Testes

- [ ] Testar salvamento de preferencias por provider.
- [ ] Testar readiness de Ollama sem chave.
- [ ] Testar readiness de Groq/NVIDIA sem chave.
- [ ] Testar fallback provider A falha, provider B responde.
- [ ] Testar que segredo nao aparece em logs.

## Criterios De Saida

- [ ] Usuario consegue alternar provider/modelo pela UI.
- [ ] Fallback e opcional, configuravel e auditavel.
- [ ] A UI nao menciona OmniRoute como provider ativo.
- [ ] Testes de UI/config passam.
