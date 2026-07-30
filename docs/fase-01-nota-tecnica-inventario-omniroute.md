# Nota Tecnica - Inventario OmniRoute

Atualizado em 2026-07-30.

## Comando Executado

```powershell
rg -n "omniroute|OMNIROUTE|OmniRoute|omnirouter|OmniRouter" app tests README.md .env.example
```

Tambem foi executada uma busca complementar por campos `provider` em `app`,
`tests` e `alembic` para identificar dados persistidos que podem guardar
`provider="omniroute"`.

## Resumo Do Acoplamento

O OmniRoute ainda esta acoplado como provider principal da aplicacao. Ele aparece
em defaults de configuracao, selecao de provider por canal, UI, providers
concretos, validacao de modelos, README, `.env.example`, testes e registros de
historico.

## Usos Por Categoria

### Configuracao E Politica

- `app/config/settings.py`: define `ai_provider="omniroute"`,
  `OMNIROUTE_TEXT_MODELS`, `omniroute_api_key`, `omniroute_base_url` e modelos
  padrao de texto, imagem, video e voz.
- `app/config/provider_policy.py`: define `DEFAULT_PROVIDER="omniroute"` e
  `SUPPORTED_AI_PROVIDERS=("omniroute",)`.
- `app/config/runtime_preferences.py`: permite persistir `OMNIROUTE_*` na pasta
  `.runtime/`.
- `.env.example` e `README.md`: documentam OmniRoute como provider padrao.

### Texto

- `app/providers/llm/omniroute.py`: implementacao concreta de chat completions
  OpenAI-compatible usando `OMNIROUTE_API_KEY` e `OMNIROUTE_BASE_URL`.
- `app/generation/model_settings.py`: instancia `OmniRouteLLMProvider` quando o
  provider efetivo e `omniroute` ou `opencode`.
- `app/storytelling/idea_lab.py` e `app/generation/service.py`: consomem o
  provider resolvido e ainda contem mensagens de erro herdadas do OmniRoute.

### Imagem

- `app/providers/image/omniroute.py`: provider concreto de imagem.
- `app/visual_bible/image_generation.py`: aceita apenas `omniroute` para imagem
  real.
- `app/storyboards/workflow.py`: aceita apenas `omniroute` para storyboard real.

### Video

- `app/providers/video/omniroute.py`: provider concreto de video com submit,
  polling e download.
- `app/video_generation/service.py`: seleciona OmniRoute como provider real de
  video.
- `app/video_generation/schemas.py`: restringe o input a `auto` ou `omniroute`.

### Voz

- `app/providers/speech/omniroute.py`: provider concreto de speech via
  OmniRoute.
- `app/providers/speech/service.py`: resolve speech provider `omniroute`, embora
  o default atual esteja separado em `openai_compatible`.

### UI, Readiness, Custos E Observabilidade

- `app/ui/routes/settings_page.py`: exibe e salva chave, base URL e modelos
  `OMNIROUTE_*`.
- `app/ui/project/workflows.py`, `app/ui/workspace/panels.py` e `app/ui/pages.py`:
  exibem provider/modelo resolvidos.
- `app/observability/service.py`: calcula readiness com base no provider efetivo.
- `app/costs/service.py` e `app/costs/schemas.py`: usam `omniroute` como default
  de custo quando nenhum provider e informado.

### Testes

- Testes especificos: `tests/test_omniroute_provider.py`,
  `tests/test_omniroute_smoke.py`, `tests/test_omniroute_video_speech.py` e
  `tests/test_omniroute_video_speech_smoke.py`.
- Testes de fluxo e UI ainda criam `Settings(ai_provider="omniroute")` ou
  esperam provider `omniroute`: `tests/test_idea_lab.py`,
  `tests/test_visual_bible.py`, `tests/test_settings.py`,
  `tests/test_provider_policy.py`, `tests/test_observability_events.py`,
  `tests/test_app_startup_readiness.py` e outros.

## Dados Persistidos Com Provider

Os seguintes modelos/tabelas podem conter historico com
`provider="omniroute"`:

- `app/generation/models.py`: `ProjectModelSetting.provider` e
  `PromptExecution.provider`.
- `app/costs/models.py`: registros de custo por provider.
- `app/observability/models.py`: eventos operacionais com provider opcional.
- `app/visual_bible/models.py`: imagens geradas com provider.
- `app/video_generation/models.py`: jobs e artefatos de video com provider.
- Migrations em `alembic/versions/*`: colunas `provider` criadas nas fases de
  dominio, storytelling, visual bible, video generation, model settings e
  operational events.

Conclusao: nao se deve reescrever historico automaticamente na fase 01. O valor
`omniroute` deve continuar legivel para historico, auditoria e custos antigos.

## Nomes Novos De Provider

- Texto local: `ollama`.
- Texto remoto Groq: `groq`.
- Texto remoto NVIDIA NIM: `nvidia_nim`.
- Imagem/video experimental via navegador: `veo_ai_free`.
- Provider legado somente leitura durante a migracao: `omniroute`.

## Mapa De Compatibilidade

| Legado | Novo destino | Regra |
| --- | --- | --- |
| `AI_PROVIDER=omniroute` | `TEXT_PROVIDER=groq` ou `TEXT_PROVIDER=ollama` | Migrar preferencia ativa para texto; manter `omniroute` apenas para leitura de dados antigos. |
| `TEXT_PROVIDER` vazio | Provider padrao novo | Resolver para o provider definido na fase 03. |
| `OMNIROUTE_API_KEY` | `GROQ_API_KEY` ou `NVIDIA_NIM_API_KEY` | Nao copiar automaticamente sem consentimento; nomes e provedores sao diferentes. |
| `OMNIROUTE_BASE_URL` | `GROQ_BASE_URL`, `NVIDIA_NIM_BASE_URL`, `OLLAMA_BASE_URL` | Separar por provider. |
| `OMNIROUTE_DEFAULT_MODEL` | `GROQ_DEFAULT_MODEL`, `NVIDIA_NIM_DEFAULT_MODEL`, `OLLAMA_DEFAULT_MODEL` | Validar por provider no salvamento. |
| `OMNIROUTE_IMAGE_MODEL` | `VEO_AI_FREE_IMAGE_MODEL` | Somente quando o provider experimental estiver habilitado. |
| `OMNIROUTE_VIDEO_MODEL` | `VEO_AI_FREE_VIDEO_MODEL` | Somente quando o provider experimental estiver habilitado. |
| `OMNIROUTE_SPEECH_MODEL` | manter decisao separada | Voz nao faz parte do trio Ollama/Groq/NVIDIA; preservar ate decisao especifica. |

## Plano De Env Vars

Adicionar nas fases seguintes:

- `TEXT_PROVIDER`
- `TEXT_PROVIDER_FALLBACKS`
- `OLLAMA_BASE_URL`
- `OLLAMA_DEFAULT_MODEL`
- `GROQ_API_KEY`
- `GROQ_BASE_URL`
- `GROQ_DEFAULT_MODEL`
- `NVIDIA_NIM_API_KEY`
- `NVIDIA_NIM_BASE_URL`
- `NVIDIA_NIM_DEFAULT_MODEL`
- `IMAGE_PROVIDER`
- `VIDEO_PROVIDER`
- `VEO_AI_FREE_ENABLED`
- `VEO_AI_FREE_SESSION_PATH`
- `VEO_AI_FREE_IMAGE_MODEL`
- `VEO_AI_FREE_VIDEO_MODEL`

Remover `OMNIROUTE_*` somente depois de a fase 07 confirmar que nao ha uso
ativo em configuracao, UI, testes e runtime preferences.

## Decisoes Da Fase 01

- Nenhuma remocao destrutiva sera feita antes da camada nova existir.
- Mensagens antigas com "OmniRoute" podem permanecer enquanto houver provider
  legado em dados persistidos ou testes de compatibilidade.
- Dados historicos com `provider="omniroute"` serao preservados.
- `.runtime/` deve permanecer ignorado pelo Git para preferencias locais,
  cookies, sessoes e arquivos gerados.
