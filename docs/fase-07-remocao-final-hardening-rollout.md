# Fase 07 - Remocao Final, Hardening E Rollout

## Objetivo

Remover OmniRoute definitivamente, consolidar os providers novos e preparar a
aplicacao para uso continuo.

## Checklist Remocao OmniRoute

- [ ] Remover `app/providers/llm/omniroute.py` quando testes legados forem migrados.
- [ ] Remover `app/providers/image/omniroute.py` quando nao houver imports legados.
- [ ] Remover `app/providers/video/omniroute.py` quando nao houver imports legados.
- [ ] Remover settings `omniroute_*` quando compatibilidade de `.runtime/` antigo for encerrada.
- [x] Remover env vars `OMNIROUTE_*` do `.env.example`.
- [x] Remover referencias OmniRoute do README.
- [x] Migrar testes centrais de provider ativo para providers novos.
- [x] Criar rotina de compatibilidade para config antiga `omniroute` -> `ollama`/`veo_ai_free`.

## Checklist Hardening

- [x] Redigir `GROQ_API_KEY`, `NVIDIA_NIM_API_KEY`, cookies e tokens em logs.
- [x] Auditar `.runtime/preferences.json` para nao ser versionado.
- [x] Auditar `.runtime/veo_free/` para nao ser versionado.
- [x] Validar readiness com todos os providers desligados.
- [x] Validar mensagens de erro para chave ausente, quota, timeout e rate limit.
- [x] Garantir que fallback nao mascare erros de contrato JSON.

## Checklist Testes

- [x] Rodar `ruff check app tests`.
- [x] Rodar `mypy app tests`.
- [x] Rodar `pytest -q`.
- [ ] Rodar smoke Ollama local.
- [x] Rodar smoke Groq quando `STORYTELLING_TEXT_PROVIDER_SMOKE=1`.
- [x] Rodar smoke NVIDIA NIM quando `STORYTELLING_TEXT_PROVIDER_SMOKE=1`.
- [x] Rodar smoke Veo AI Free apenas manual/opt-in.

## Checklist Rollout

- [x] Atualizar README com setup de Ollama, Groq e NVIDIA.
- [x] Atualizar docs de troubleshooting.
- [x] Criar guia de reconexao Veo AI Free.
- [x] Criar guia de selecao de modelos por tarefa.
- [x] Criar plano de rollback para provider anterior por config.
- [ ] Fazer backup de `.runtime/preferences.json` antes da primeira execucao real.

## Criterios De Saida

- [x] OmniRoute nao aparece mais como provider ativo.
- [x] Texto funciona com ao menos dois providers novos em testes sem rede.
- [x] A aplicacao inicia sem chave de provider externo quando Ollama estiver configurado.
- [x] Veo AI Free permanece marcado como experimental.
- [x] Documentacao e testes refletem a arquitetura nova para providers ativos.
