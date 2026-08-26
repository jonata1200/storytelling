# Baseline e inventário da migração

Registro coletado em 2026-08-26 antes de alterações de comportamento.

## Git

- Branch observada: `main`
- SHA baseline: `3a7b1aa8ebf9338b82ab0cdb062a1c98e44e43ff`
- Worktree observado antes do registro: limpo
- Branch de migração criada: `feat/meta-vibes-migration`.

## Checks

| Check | Resultado de baseline |
| --- | --- |
| `python -m pytest` | 315 passed, 1 skipped (33.21s) |
| `python -m mypy app` | Sucesso, 168 arquivos |
| `python -m ruff check .` | Falha preexistente, 3 erros em `scripts/reset_database.py` |

O Ruff reportou `E402` nas linhas 14 e 15 e `I001` no bloco de imports iniciado na linha 14.
Esse problema não foi corrigido na Fase 00 para que o baseline permaneça explícito.

## Inventário de acoplamentos legados

### Configuração e factories

- `app/config/settings.py`: defaults, chaves, URLs e modelos Ollama/OpenRouter.
- `app/config/provider_policy.py`: providers suportados e defaults fechados nos legados.
- `app/config/runtime_preferences.py` e `app/config/api_keys.py`: persistência e validação.
- `app/generation/model_settings.py`: instancia `OllamaCloudLLMProvider` diretamente.
- `app/factory.py`: composição de providers a revisar na Fase 01.

### Providers e pipeline

- `app/providers/llm/ollama_cloud.py`: adapter textual legado.
- `app/providers/video/openrouter.py`: adapter de vídeo legado.
- `app/video_generation/continuous_generation.py`: instancia OpenRouter diretamente, usa
  constantes de polling, diretório `openrouter_videos` e metadata `openrouter_job_id`.
- `app/video_generation/continuous_review.py`: linguagem e fluxo específicos do OpenRouter.
- `app/costs/service.py` e schemas: defaults/pricing específicos do OpenRouter.
- `app/observability/service.py`: lista de providers derivada da política legada.

### Interface e documentação ativa

- `app/ui/routes/settings_page.py`: formulários e persistência Ollama/OpenRouter.
- `app/ui/workspace/panels.py`: modelos e status Ollama Cloud.
- `app/ui/workspace/video_area.py` e `storyboard_video_area.py`: mensagens OpenRouter.
- `README.md`: exemplo de ambiente apenas com providers legados.

### Testes e fixtures

- Providers: `test_ollama_cloud_llm_provider.py`, `test_openrouter_video.py`,
  `test_openai_compatible_llm_provider.py` e `test_text_provider_smoke.py`.
- Política/configuração: `test_settings.py`, `test_provider_policy.py`, `test_api_keys.py`,
  `test_runtime.py`, `test_production_settings.py` e `test_app_startup_readiness.py`.
- Custos/observabilidade/storage: `test_costs.py`, `test_costs_router.py`,
  `test_observability_events.py`, `test_storage_governance.py` e casos auxiliares.
- `tests/conftest.py` limpa variáveis de provider para isolamento.

## Variáveis encontradas

`AI_PROVIDER`, `TEXT_PROVIDER`, `TEXT_PROVIDER_FALLBACKS`, `VIDEO_PROVIDER`,
`OLLAMA_CLOUD_API_KEY`, `OLLAMA_CLOUD_BASE_URL`, `OLLAMA_CLOUD_DEFAULT_MODEL`,
`OPENROUTER_API_KEY`, `OPENROUTER_VIDEO_MODEL`, `OPENROUTER_VIDEO_BASE_URL` e
`OPENROUTER_VIDEO_GENERATE_AUDIO`.

## Próxima ação local

Depois de obter as evidências externas descritas nos documentos de integração, atualizar a ADR
para aceita. Em paralelo, a Fase 01 pode começar pela registry/factory e por remover a
instanciação concreta no fluxo contínuo, mantendo os adapters legados disponíveis.
