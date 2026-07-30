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

- [x] Criar seletor `Provider de texto`: Ollama, Groq, NVIDIA NIM.
- [x] Mostrar campos especificos do provider selecionado.
- [x] Permitir salvar chaves de Groq e NVIDIA NIM pela UI.
- [x] Permitir editar base URL de Ollama e NVIDIA NIM.
- [x] Mostrar lista selecionavel de modelos por provider.
- [x] Se um modelo salvo nao estiver na lista, inclui-lo como opcao adicional.
- [x] Remover textos e campos OmniRoute.
- [x] Atualizar copy da pagina para explicar fallback.

## Checklist Fallback

- [x] Adicionar `TEXT_PROVIDER_FALLBACKS`.
- [x] Implementar fallback opcional em `run_structured_generation`.
- [x] Registrar provider primario e provider final usado.
- [x] Nao fazer fallback quando erro for validacao de prompt/JSON recuperavel.
- [x] Fazer fallback em timeout, 429, 5xx e erro de rede.
- [x] Nao fazer fallback em erro de chave ausente sem notificar claramente.

## Checklist Observabilidade

- [x] Atualizar readiness para listar `text_provider`.
- [x] Incluir detalhes: provider, base_url, model, api_key_configured.
- [x] Registrar falhas por provider em `OperationalEvent`.
- [x] Registrar fallback em `PromptExecution.parameters`.
- [x] Redigir chaves em logs e eventos.

## Checklist Testes

- [x] Testar salvamento de preferencias por provider.
- [x] Testar readiness de Ollama sem chave.
- [x] Testar readiness de Groq/NVIDIA sem chave.
- [x] Testar fallback provider A falha, provider B responde.
- [x] Testar que segredo nao aparece em logs.

## Criterios De Saida

- [x] Usuario consegue alternar provider/modelo pela UI.
- [x] Fallback e opcional, configuravel e auditavel.
- [x] A UI nao menciona OmniRoute como provider ativo.
- [x] Testes de UI/config passam.
