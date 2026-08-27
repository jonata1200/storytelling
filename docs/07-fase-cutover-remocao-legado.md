# Fase 07 — Cutover e remoção total de Ollama/OpenRouter

## Objetivo

Tornar Meta + Vibes os únicos providers da aplicação e remover completamente código, configuração, UI e testes ativos específicos de Ollama Cloud e OpenRouter.

## Estado da implementação (2026-08-27)

Cutover de código concluído:

- Meta é o único provider registrado para texto e imagem; Vibes é o único para vídeo.
- Adapters, factories, settings, credenciais, pricing, UI e testes exclusivos dos providers
  removidos foram apagados.
- Preferências antigas são ignoradas no boot e podem ser limpas por
  `cleanup_obsolete_runtime_preferences`; model settings de projetos antigos migram para Meta
  sob demanda.
- Assets, diretórios e metadata históricos continuam sendo lidos sem troca do provider original.
- A busca de resíduos em código ativo retorna apenas fixtures de paths históricos intencionais em
  `tests/test_storage_governance.py` e `tests/_project_creation_flow_cases.py`.
- `pytest`, `ruff check .`, `mypy app`, `git diff --check` e
  `docker compose config --quiet` estão aprovados.

Gates externos ainda pendentes antes de declarar o cutover pronto para produção:

- aprovar as fases anteriores e o smoke real de ponta a ponta com a conta Meta/Vibes;
- criar backup do banco e tag/commit de rollback;
- instalar/autorizar o adapter browser real do Vibes e executar os smokes pagos;
- rotacionar credenciais antigas nos respectivos serviços (ação externa);
- executar auditoria de dependências quando `pip-audit` estiver disponível.

Esta fase só começa após Meta Text, Meta Visual e Vibes Video estarem aprovados no fluxo de ponta a ponta.

## Pré-condições

- [ ] Fase 02 aprovada.
- [ ] Fase 03 aprovada.
- [ ] Fase 04 aprovada.
- [ ] Fase 05 aprovada.
- [ ] Fase 06 aprovada.
- [ ] Smoke real `ideia → roteiro → visual bible → video` aprovado.
- [ ] Backup do banco de desenvolvimento criado.
- [ ] Tag/commit de rollback criado antes do cutover.

## Resultado final de providers

```text
TEXT_PROVIDER=meta
IMAGE_PROVIDER=meta
VIDEO_PROVIDER=vibes
```

Nenhuma opção Ollama/OpenRouter aparece na UI.

## Checklist — remover código Ollama

- [ ] Apagar `app/providers/llm/ollama_cloud.py`.
- [ ] Remover imports de Ollama.
- [ ] Remover `SUPPORTED_TEXT_PROVIDERS` legado.
- [ ] Remover `OLLAMA_CLOUD_TEXT_MODELS`.
- [ ] Remover `LOCKED_OLLAMA_CLOUD_TEXT_MODEL`.
- [ ] Remover normalizadores específicos de Ollama.
- [ ] Remover fallback para Ollama.
- [ ] Remover mensagens de erro Ollama.
- [ ] Remover testes exclusivos do provider Ollama.
- [ ] Preservar testes de contrato genérico que continuam úteis.

## Checklist — remover código OpenRouter

- [ ] Apagar `app/providers/video/openrouter.py`.
- [ ] Remover imports de OpenRouter.
- [ ] Remover factory branch `openrouter`.
- [ ] Remover `SUPPORTED_VIDEO_PROVIDERS` legado.
- [ ] Remover retry/constants OpenRouter.
- [ ] Remover mensagens de erro OpenRouter.
- [ ] Remover testes exclusivos OpenRouter.
- [ ] Remover qualquer fallback automático para OpenRouter.

## Checklist — Settings

Remover:

- [ ] `ai_provider` se não tiver mais função real.
- [ ] `ollama_cloud_api_key`.
- [ ] `ollama_cloud_base_url`.
- [ ] `ollama_cloud_default_model`.
- [ ] `openrouter_api_key`.
- [ ] `openrouter_video_model`.
- [ ] `openrouter_video_base_url`.
- [ ] `openrouter_video_generate_audio`.
- [ ] qualquer campo legado correlato.

Manter/adotar:

- [ ] `text_provider = "meta"` ou eliminar escolha se for sempre Meta.
- [ ] `image_provider = "meta"` ou eliminar escolha se for sempre Meta.
- [ ] `video_provider = "vibes"` ou eliminar escolha se for sempre Vibes.
- [ ] `meta_*`.
- [ ] `vibes_*`.
- [ ] `ffmpeg_path`.
- [ ] configurações de storage/Redis/PostgreSQL.

## Checklist — `.env.example`

- [ ] Remover `AI_PROVIDER=ollama_cloud`.
- [ ] Remover `TEXT_PROVIDER=ollama_cloud`.
- [ ] Remover `OLLAMA_CLOUD_*`.
- [ ] Remover `VIDEO_PROVIDER=openrouter`.
- [ ] Remover `OPENROUTER_*`.
- [ ] Adicionar somente variáveis Meta.
- [ ] Adicionar somente variáveis Vibes.
- [ ] Documentar browser profile sem secret.
- [ ] Manter `.env.example` sem valores reais.

## Checklist — runtime preferences

- [ ] Mapear preferências antigas persistidas.
- [ ] Migrar projetos para Meta/Vibes.
- [ ] Ignorar com segurança chaves antigas desconhecidas.
- [ ] Remover opções antigas da UI.
- [ ] Não quebrar boot caso um runtime preference antigo ainda exista.
- [ ] Criar cleanup opcional das chaves obsoletas.

## Checklist — storage e metadata

Não apagar histórico.

- [ ] Continuar aceitando leitura de assets em `openrouter_videos/` antigos.
- [ ] Novos vídeos somente em `generated_videos/`.
- [ ] Continuar exibindo `provider="openrouter"` em assets históricos.
- [ ] Não fingir que assets históricos foram gerados pelo Vibes.
- [ ] Preservar `openrouter_job_id` histórico como metadata imutável.
- [ ] Novos assets usar `provider_job_id`.
- [ ] Não executar migration destrutiva desnecessária em metadata JSON.

## Checklist — custos

- [ ] Remover pricing/configuração ativa de Ollama.
- [ ] Remover pricing/configuração ativa de OpenRouter.
- [ ] Adicionar Meta quando custo for mensurável.
- [ ] Adicionar Vibes quando custo for mensurável.
- [ ] Tratar `unknown/not_reported` sem quebrar orçamento.
- [ ] Preservar histórico de CostEntry legado.

## Checklist — UI

- [ ] Remover Ollama das configurações.
- [ ] Remover OpenRouter das configurações.
- [ ] Remover textos `Seedance/OpenRouter`.
- [ ] Mostrar Meta no texto.
- [ ] Mostrar Meta na biblioteca visual.
- [ ] Mostrar Vibes no vídeo somente onde isso ajuda o usuário.
- [ ] Atualizar mensagens de falta de credencial.
- [ ] Atualizar telas de setup.
- [ ] Atualizar status/health de provider.
- [ ] Garantir que a aplicação não peça chaves antigas.

## Checklist — documentação

- [ ] Atualizar README.
- [ ] Atualizar instalação.
- [ ] Atualizar `.env.example`.
- [ ] Atualizar arquitetura.
- [ ] Atualizar fluxo de vídeo.
- [ ] Remover instruções OpenRouter.
- [ ] Remover instruções Ollama.
- [ ] Documentar Meta Model API.
- [ ] Documentar Meta Image integration mode.
- [ ] Documentar Vibes integration mode.
- [ ] Documentar login/session browser quando aplicável.
- [ ] Documentar worker.
- [ ] Documentar FFmpeg.
- [ ] Documentar troubleshooting.

## Checklist — dependências

- [ ] Remover dependências que só existiam para providers antigos, se houver.
- [ ] Adicionar Playwright apenas se o modo browser for realmente usado.
- [ ] Fixar versão do Playwright.
- [ ] Documentar instalação dos browsers Playwright.
- [ ] Atualizar `requirements.lock`.
- [ ] Atualizar `pyproject.toml`.
- [ ] Verificar vulnerabilidades/dependências obsoletas.

## Checklist — busca por resíduos

Executar busca no código ativo:

```text
ollama
ollama_cloud
OLLAMA_
openrouter
OpenRouter
OPENROUTER_
seedance
```

- [ ] Não deve existir referência ativa a Ollama.
- [ ] Não deve existir referência ativa a OpenRouter.
- [ ] Exceções permitidas somente em migrations/documentação histórica explicitamente necessária.
- [ ] Revisar comentários.
- [ ] Revisar testes.
- [ ] Revisar scripts.
- [ ] Revisar README.
- [ ] Revisar UI.
- [ ] Revisar `.github`.
- [ ] Revisar `.env.example`.

## Checklist — segurança

- [ ] Rotacionar/remover chaves Ollama antigas.
- [ ] Rotacionar/remover chave OpenRouter antiga.
- [ ] Remover secrets antigos de runtime preferences.
- [ ] Confirmar `.gitignore` para browser profiles.
- [ ] Rodar secret scan.
- [ ] Confirmar redaction de Meta.
- [ ] Confirmar redaction de Vibes.
- [ ] Confirmar que screenshots de diagnóstico não contêm credenciais visíveis.

## Checklist — testes finais

- [ ] Unit tests.
- [ ] Integration tests.
- [ ] Provider tests.
- [ ] UI tests.
- [ ] Security tests.
- [ ] Ruff.
- [ ] mypy.
- [ ] Smoke Meta Text.
- [ ] Smoke Meta Image.
- [ ] Smoke Vibes Video.
- [ ] Fluxo completo de projeto novo.
- [ ] Abrir projeto legado.
- [ ] Visualizar asset OpenRouter histórico.
- [ ] Reiniciar aplicação durante job e validar recuperação.
- [ ] Gerar pelo menos 3 shots consecutivos com continuidade.
- [ ] Regenerar apenas o shot intermediário.
- [ ] Montar vídeo final.

## Critérios de aceite final

- [ ] A aplicação inicia sem qualquer variável Ollama/OpenRouter.
- [ ] Nenhuma tela oferece Ollama/OpenRouter.
- [ ] Nenhum código ativo instancia Ollama/OpenRouter.
- [ ] Meta executa todo o texto.
- [ ] Meta produz a biblioteca visual.
- [ ] Vibes produz os vídeos.
- [ ] Projetos históricos continuam abrindo.
- [ ] Assets históricos preservam provider original.
- [ ] Todos os checks estão verdes.
- [ ] README descreve apenas a arquitetura atual.
- [ ] A branch está pronta para merge na `main`.

## Definição de pronto do projeto de migração

O projeto só é considerado migrado quando este comando conceitual não encontra dependências funcionais do legado:

```text
rg -n "ollama|openrouter|OLLAMA_|OPENROUTER_" app tests scripts README.md .env.example
```

Referências históricas conscientemente preservadas devem estar documentadas e não participar da execução atual.
