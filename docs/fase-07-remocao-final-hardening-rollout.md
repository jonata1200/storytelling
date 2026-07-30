# Fase 07 - Remocao Final, Hardening E Rollout

## Objetivo

Remover OmniRoute definitivamente, consolidar os providers novos e preparar a
aplicacao para uso continuo.

## Checklist Remocao OmniRoute

- [ ] Remover `app/providers/llm/omniroute.py` se nao houver compatibilidade pendente.
- [ ] Remover `app/providers/image/omniroute.py` quando imagem tiver alternativa.
- [ ] Remover `app/providers/video/omniroute.py` quando video tiver alternativa.
- [ ] Remover settings `omniroute_*`.
- [ ] Remover env vars `OMNIROUTE_*` do `.env.example`.
- [ ] Remover referencias OmniRoute do README.
- [ ] Remover testes `test_omniroute_*` ou migra-los para providers novos.
- [ ] Criar migration ou rotina de compatibilidade para registros antigos.

## Checklist Hardening

- [ ] Redigir `GROQ_API_KEY`, `NVIDIA_NIM_API_KEY`, cookies e tokens em logs.
- [ ] Auditar `.runtime/preferences.json` para nao ser versionado.
- [ ] Auditar `.runtime/veo_free/` para nao ser versionado.
- [ ] Validar readiness com todos os providers desligados.
- [ ] Validar mensagens de erro para chave ausente, quota, timeout e rate limit.
- [ ] Garantir que fallback nao mascare erros de contrato JSON.

## Checklist Testes

- [ ] Rodar `ruff check app tests`.
- [ ] Rodar `mypy app tests`.
- [ ] Rodar `pytest -q`.
- [ ] Rodar smoke Ollama local.
- [ ] Rodar smoke Groq quando `RUN_PROVIDER_SMOKE_TESTS=1`.
- [ ] Rodar smoke NVIDIA NIM quando `RUN_PROVIDER_SMOKE_TESTS=1`.
- [ ] Rodar smoke Veo AI Free apenas manual/opt-in.

## Checklist Rollout

- [ ] Atualizar README com setup de Ollama, Groq e NVIDIA.
- [ ] Atualizar docs de troubleshooting.
- [ ] Criar guia de reconexao Veo AI Free.
- [ ] Criar guia de selecao de modelos por tarefa.
- [ ] Criar plano de rollback para provider anterior por config.
- [ ] Fazer backup de `.runtime/preferences.json` antes da primeira execucao real.

## Criterios De Saida

- [ ] OmniRoute nao aparece mais como provider ativo.
- [ ] Texto funciona com ao menos dois providers novos.
- [ ] A aplicacao inicia sem chave de provider externo quando Ollama estiver configurado.
- [ ] Veo AI Free permanece marcado como experimental.
- [ ] Documentacao e testes refletem a arquitetura nova.
