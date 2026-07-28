# Auditoria OpenRouter para migração OmniRoute

## Escopo revisado

- Configuração: `app/config/settings.py`, `app/config/model_policy.py`,
  `app/config/provider_policy.py`, `app/config/preferences.py`,
  `app/config/runtime_preferences.py`.
- Texto/LLM: `app/generation/model_settings.py`,
  `app/generation/service.py`, `app/providers/llm/openrouter.py`,
  `app/storytelling/idea_lab.py`.
- Imagem: `app/providers/image/openrouter.py`,
  `app/visual_bible/image_generation.py`, `app/storyboards/workflow.py`.
- Vídeo: `app/providers/video/openrouter.py`,
  `app/video_generation/service.py`, `app/video_generation/schemas.py`.
- Speech: `app/providers/speech/openai_compatible.py`,
  `app/providers/speech/service.py`.
- UI: `app/ui/routes/settings_page.py`,
  `app/ui/workspace/panels.py`, `app/ui/project/actions.py`.
- Observabilidade: `app/observability/service.py`,
  `app/observability/redaction.py`.
- Custos/testes: `app/costs/service.py`, `tests/test_openrouter_provider.py`,
  `tests/test_openrouter_media_providers.py`, `tests/test_provider_policy.py`,
  `tests/test_settings.py`, `tests/test_security_regressions.py`.

## Dependências por categoria

- Texto: usa OpenRouter em `/chat/completions` via
  `OpenRouterLLMProvider`; seleção por tarefa fica em
  `ProjectModelSetting.provider/model`.
- Imagem: usa OpenRouter Images em `/images`; referências visuais e
  storyboards reutilizam o mesmo provider.
- Vídeo: usa OpenRouter Videos em `/videos`, `/videos/{id}` e
  `/videos/{id}/content?index=0`.
- Speech: não depende de OpenRouter; usa provider OpenAI-compatible separado.
- Configuração: variáveis `OPENROUTER_*` continuam ativas; fase 2 adiciona
  `AI_PROVIDER`, overrides por mídia e variáveis `OMNIROUTE_*`.
- UI: tela de configurações e workspace antes mencionavam apenas OpenRouter;
  fase 2 generaliza para provedores de IA.
- Custos: custos são registrados por `provider`, `model` e `operation`, sem
  acoplamento estrutural a OpenRouter.
- Testes: testes OpenRouter seguem como contrato do provider atual; novos testes
  cobrem a política genérica e settings OmniRoute.

## Endpoints OmniRoute previstos

- Texto: `POST /v1/chat/completions`.
- Imagem: `POST /v1/images/generations` ou rota compatível exposta pelo gateway
  escolhido.
- Vídeo: rota de geração/polling compatível a confirmar na fase 5.
- Speech: sem migração obrigatória nesta etapa; provider de voz permanece
  `openai_compatible`.

## URL base e chave

- SaaS previsto: `https://omnirouters.com/v1`.
- Local previsto: URL configurável por `OMNIROUTE_BASE_URL`.
- Chave OmniRoute: aceita token não vazio, sem prefixo obrigatório confirmado.
- Chave OpenRouter: continua exigindo prefixo `sk-or-`.

## Matriz inicial de modelos

| Uso | OpenRouter atual | OmniRoute inicial |
| --- | --- | --- |
| Texto | `OPENROUTER_DEFAULT_MODEL` | `OMNIROUTE_DEFAULT_MODEL` |
| Imagem | `OPENROUTER_IMAGE_MODEL` | `OMNIROUTE_IMAGE_MODEL` |
| Vídeo | `OPENROUTER_VIDEO_MODEL` | `OMNIROUTE_VIDEO_MODEL` |
| Speech | `SPEECH_MODEL` | Sem troca nesta fase |

## Incompatibilidades conhecidas

- Prefixo de chave: OpenRouter usa `sk-or-`; OmniRoute fica flexível até a
  confirmação final do gateway.
- Vídeo: endpoints e formato de polling podem não ser idênticos ao provider
  OpenRouter atual.
- Imagem: a aplicação usa fallback de parâmetros para erros específicos do
  OpenRouter Images; esses fallbacks precisam ser reavaliados no provider
  OmniRoute.
- Headers `HTTP-Referer` e `X-OpenRouter-Title` são específicos de OpenRouter.

## Rollout

- OpenRouter permanece como provider padrão e fallback temporário.
- OmniRoute pode ser configurado e salvo; texto e imagem já possuem providers
  reais, enquanto vídeo permanece em OpenRouter até a fase específica.
- Mocks seguem bloqueados no fluxo da aplicação.
