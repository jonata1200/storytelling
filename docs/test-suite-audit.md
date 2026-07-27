# Relatorio da suite de testes

## Resumo executivo

A aplicacao tem uma suite grande, mas a maior parte dela ainda tem serventia. O volume atual e explicado pelo tipo de sistema: ha fluxos de IA, upload de arquivos, referencias visuais, geracao de roteiro, assets, video, custos, seguranca, storage, observabilidade e UI. Esses pontos sao propensos a regressao porque dependem de contratos estruturados, validacao de payloads, estados intermediarios e comportamento assicrono.

Inventario atual:

- 43 arquivos de teste coletaveis pelo pytest.
- 301 testes coletados.
- 3 modulos internos concentram casos migrados mecanicamente: `_project_creation_flow_cases.py`, `_project_agent_cases.py` e `_storytelling_normalization_cases.py`.
- Ultima validacao completa registrada apos as fases 1 a 5: `301 passed`, com 1 aviso de deprecacao do Starlette/FastAPI TestClient.
- Arquivos de coleta mais relevantes apos a reorganizacao: `test_project_creation_ui.py`, `test_project_creation_assets.py`, `test_project_creation_storyboard.py`, `test_project_creation_workspace.py`, `test_project_agent_routing.py`, `test_project_agent_script.py`, `test_project_agent_visual.py`, `test_project_agent_storyboard_video.py`, `test_storytelling_idea_normalization.py`, `test_storytelling_script_normalization.py` e `test_storytelling_story_bible_compatibility.py`.

Conclusao: nao recomendo remover testes em massa. As fases 1 a 5 ja reorganizaram arquivos grandes, consolidaram testes pequenos, reduziram o legado de Story Bible, deixaram providers mock como ferramentas de teste com smoke coverage minima e criaram cortes por marcador para execucao local.

## Status de implementacao

Fases implementadas:

- Fase 1 concluida: os arquivos grandes foram divididos em arquivos de coleta por dominio, mantendo os casos originais em modulos internos para evitar reescrita arriscada.
- Fase 2 concluida: `test_health.py`, `test_story_ideas_ordering.py` e `test_director_agent.py` foram consolidados em arquivos de dominio.
- Fase 3 concluida: Story Bible deixou de ser tratado como pipeline ativo nos testes e ficou restrito a compatibilidade/fallback.
- Fase 4 concluida: providers mock ficaram com um smoke test por provider nos arquivos proprios.
- Fase 5 concluida: a suite agora possui marcadores `unit`, `integration`, `provider`, `ui` e `security`, aplicados automaticamente por dominio.

Arquivos criados na fase 1:

- `test_project_creation_ui.py`
- `test_project_creation_assets.py`
- `test_project_creation_storyboard.py`
- `test_project_creation_workspace.py`
- `test_project_agent_routing.py`
- `test_project_agent_script.py`
- `test_project_agent_visual.py`
- `test_project_agent_storyboard_video.py`
- `test_storytelling_idea_normalization.py`
- `test_storytelling_script_normalization.py`
- `test_storytelling_story_bible_compatibility.py`

Arquivos consolidados na fase 2:

- `test_health.py` foi absorvido por `test_auth.py`.
- `test_story_ideas_ordering.py` foi absorvido por `test_idea_lab.py`.
- `test_director_agent.py` foi absorvido por `test_project_agent_routing.py`, usando o modulo interno `_project_agent_cases.py`.

Marcadores disponiveis:

- `unit`: 52 testes coletados.
- `integration`: 121 testes coletados.
- `provider`: 87 testes coletados.
- `ui`: 68 testes coletados.
- `security`: 39 testes coletados.

Comandos locais recomendados:

```bash
pytest
pytest -m unit
pytest -m "not integration"
pytest -m integration
pytest -m provider
pytest -m ui
pytest -m security
```

O CI continua executando a suite completa e agora tambem valida a cobertura dos marcadores com coleta antes da etapa `pytest`.

## Resposta direta

E necessario ter tantos testes?

Sim, em boa parte. O numero alto e justificavel porque a aplicacao tem muitos pontos sensiveis:

- Contratos de IA precisam aceitar saidas variaveis, incompletas ou malformadas.
- Uploads de PDF, DOCX e imagens precisam validar extensao, tamanho, path traversal e metadados.
- Fluxos de criacao de projeto mexem em estado, arquivos, jobs e interface.
- Seguranca, custos e storage sao areas onde regressao pequena pode ter impacto grande.
- Providers externos precisam de testes de erro, timeout, retry e fallback.

Existem testes antigos sem serventia?

Ainda existem testes que podem ser fundidos, renomeados ou removidos em fases futuras, principalmente nos grupos de Visual Bible, OpenRouter media providers e UI de criacao. Os candidatos iniciais de Story Bible legado, providers mock e arquivos pequenos ja foram tratados nas fases 1 a 4.

## Classificacao geral

### Manter como prioridade alta

Esses grupos protegem comportamento critico e devem continuar existindo:

- `test_security_regressions.py`
- `test_quality_security.py`
- `test_auth.py`
- `test_storage_governance.py`
- `test_costs.py`
- `test_reference_upload.py`
- `test_script_upload.py`
- `test_openrouter_provider.py`
- `test_openrouter_media_providers.py`
- `test_prompt_compiler.py`
- `test_visual_bible.py`
- `test_visual_bible_script_profiles.py`
- `test_storytelling_normalization_flow.py`, ja dividido em arquivos de coleta por dominio
- `test_project_creation_flow.py`, ja dividido em arquivos de coleta por dominio
- `test_project_agent.py`, ja dividido em arquivos de coleta por dominio
- `test_project_bulk_delete.py`
- `test_video_retry.py`
- `test_video_durations.py`
- `test_storyboard_timeline.py`
- `test_finalization_profile.py`
- `test_observability_events.py`
- `test_observability_middleware.py`

### Manter, mas reorganizar

Esses testes parecem importantes, mas os arquivos estao grandes ou misturam responsabilidades:

- `test_project_creation_flow.py`, implementado via arquivos de coleta por dominio
- `test_project_agent.py`, implementado via arquivos de coleta por dominio
- `test_storytelling_normalization_flow.py`, implementado via arquivos de coleta por dominio
- `test_visual_bible.py`
- `test_visual_bible_script_profiles.py`
- `test_openrouter_media_providers.py`
- `test_idea_lab.py`
- `test_initial_script_pipeline.py`

### Revisar antes de remover

Esses arquivos ou grupos podem conter testes antigos, redundantes ou de baixo valor isolado:

- `test_mock_llm_provider.py`, ja reduzido a smoke test
- `test_mock_image_provider.py`, ja reduzido a smoke test
- `test_mock_speech_provider.py`, ja reduzido a smoke test
- `test_mock_video_provider.py`, ja reduzido a smoke test
- `test_director_agent.py`, ja consolidado em `test_project_agent_routing.py`
- `test_health.py`, ja consolidado em `test_auth.py`
- `test_story_ideas_ordering.py`, ja consolidado em `test_idea_lab.py`
- Testes de Story Bible legado ja revisados em `test_initial_script_pipeline.py` e `test_storytelling_story_bible_compatibility.py`; `test_visual_bible.py` ainda usa compatibilidade de payload visual.

## Analise por arquivo

| Arquivo | Testes | Linhas | Valor | Recomendacao |
| --- | ---: | ---: | --- | --- |
| `test_auth.py` | 5 | 68 | Alto | Manter. Cobre autenticacao e endpoints publicos/privados. Absorveu `test_health.py`. |
| `test_costs.py` | 4 | 45 | Alto | Manter. Area financeira/custos e sensivel. |
| `test_dependencies.py` | 3 | 91 | Medio/alto | Manter. Ajuda a proteger grafo de dependencias entre artefatos. |
| `test_director_agent.py` | 0 | 0 | Consolidado | Removido como arquivo separado; caso migrado para `test_project_agent_routing.py`. |
| `test_finalization_profile.py` | 6 | 91 | Alto | Manter. Fase recente e ligada a entrega final. |
| `test_health.py` | 0 | 0 | Consolidado | Removido como arquivo separado; caso migrado para `test_auth.py`. |
| `test_idea_lab.py` | 17 | 513 | Alto | Manter. Cobre laboratorio de ideias, validacao, filtros, persistencia e ordenacao por data. |
| `test_initial_script_pipeline.py` | 5 | 279 | Medio/alto | Manter. Garante que a criacao inicial usa roteiro e que o pipeline inicial de Story Bible continua removido. |
| `test_mock_image_provider.py` | 1 | 28 | Medio | Reduzido a smoke test do contrato minimo do provider de imagem. |
| `test_mock_llm_provider.py` | 1 | 27 | Medio | Reduzido a smoke test do contrato minimo do provider LLM. |
| `test_mock_speech_provider.py` | 1 | 25 | Medio | Manter como smoke test ou consolidar com outros mocks. |
| `test_mock_video_provider.py` | 1 | 27 | Medio | Reduzido a smoke test do contrato minimo do provider de video. |
| `test_observability_events.py` | 3 | 65 | Alto | Manter. Observabilidade foi fase recente e regressao aqui reduz visibilidade de falhas. |
| `test_observability_middleware.py` | 1 | 13 | Alto | Manter. Pequeno e protege correlation id. |
| `test_openrouter_media_providers.py` | 16 | 529 | Alto | Manter. Dividir em imagem e video se crescer mais. |
| `test_openrouter_provider.py` | 7 | 81 | Alto | Manter. Protege integracao de LLM e parametros de requisicao. |
| `test_production_settings.py` | 9 | 67 | Alto | Manter. Bloqueia mocks/free models e protege configuracao de producao. |
| `test_project_agent.py` | 21 | 1064 | Alto | Dividido em `test_project_agent_routing.py`, `test_project_agent_script.py`, `test_project_agent_visual.py` e `test_project_agent_storyboard_video.py`; casos preservados em `_project_agent_cases.py`. |
| `test_project_bulk_delete.py` | 8 | 221 | Alto | Manter. Delecao em massa e area destrutiva. |
| `test_project_creation_flow.py` | 46 | 1111 | Alto | Dividido em `test_project_creation_ui.py`, `test_project_creation_assets.py`, `test_project_creation_storyboard.py` e `test_project_creation_workspace.py`; casos preservados em `_project_creation_flow_cases.py`. |
| `test_prompt_compiler.py` | 10 | 253 | Alto | Manter. Protege prompts, fallback e erros de provider. |
| `test_quality_continuity.py` | 3 | 45 | Alto | Manter. Pequeno e relevante para consistencia narrativa. |
| `test_quality_security.py` | 2 | 14 | Alto | Manter. Pequeno e sensivel. |
| `test_reference_upload.py` | 5 | 111 | Alto | Manter. Recurso recente de referencias visuais, incluindo categoria automatica. |
| `test_script_upload.py` | 3 | 40 | Alto | Manter. Recurso recente de upload de PDF/DOCX. |
| `test_security_regressions.py` | 11 | 178 | Alto | Manter. Suite de regressao critica. |
| `test_settings.py` | 2 | 13 | Medio/alto | Manter. Pequeno e barato. |
| `test_speech_provider.py` | 1 | 52 | Medio | Manter se audio ainda faz parte do fluxo; caso contrario, marcar como legado. |
| `test_state_machine.py` | 2 | 14 | Alto | Manter. Pequeno e protege transicoes. |
| `test_storage_governance.py` | 4 | 100 | Alto | Manter. Storage e retencao sao areas de risco. |
| `test_story_ideas_ordering.py` | 0 | 0 | Consolidado | Removido como arquivo separado; caso migrado para `test_idea_lab.py`. |
| `test_storyboard_timeline.py` | 15 | 476 | Alto | Manter. Protege storyboard e timeline. |
| `test_storytelling_normalization_flow.py` | 26 | 637 | Alto, com compatibilidade | Dividido em `test_storytelling_idea_normalization.py`, `test_storytelling_script_normalization.py` e `test_storytelling_story_bible_compatibility.py`; casos preservados em `_storytelling_normalization_cases.py`. |
| `test_subtitles.py` | 3 | 32 | Medio/alto | Manter se legendas seguem no fluxo de video. |
| `test_video_durations.py` | 3 | 30 | Alto | Manter. Pequeno e protege duracao/custos/geracao. |
| `test_video_retry.py` | 7 | 175 | Alto | Manter. Retry/idempotencia sao criticos em jobs externos. |
| `test_visual_bible.py` | 33 | 589 | Alto | Manter, mas dividir em prompts, provider, parsing e referencias. |
| `test_visual_bible_script_profiles.py` | 16 | 616 | Alto | Manter. Recurso complexo e recente; pode ser dividido depois. |

## Pontos de redundancia ou manutencao dificil

### 1. `test_project_creation_flow.py`

Este e o principal candidato a reorganizacao. Ele tem 46 testes e 1111 linhas, cobrindo muitos dominios diferentes. O problema nao e a existencia dos testes, e sim o arquivo ter virado um ponto unico para qualquer regressao de UI/projeto.

Recomendacao:

- Criar `test_project_creation_ui.py` para helpers de UI, titulos, botoes, tabs e formatacao.
- Criar `test_project_creation_assets.py` para URLs de asset, path traversal e referencias visuais.
- Criar `test_project_creation_storyboard.py` para prompts, aprovacao e geracao de storyboard.
- Criar `test_project_creation_workspace.py` para navegacao, refresh, estado e etapas de producao.

Status implementado: casos preservados em `_project_creation_flow_cases.py` e expostos por arquivos de coleta menores.

### 2. `test_project_agent.py`

Tem alto valor, mas mistura decisoes do agente, acoes em lote, etapas, progresso, qualidade, assets e finalizacao. Isso dificulta saber se uma falha veio do roteamento do agente ou de um fluxo especifico.

Recomendacao:

- Separar testes de roteamento/conversa.
- Separar testes de execucao de acoes.
- Separar testes de progresso/estado.
- Separar testes de finalizacao/qualidade.

Status implementado: casos preservados em `_project_agent_cases.py` e expostos por arquivos de coleta menores.

### 3. `test_storytelling_normalization_flow.py`

E importante porque protege normalizacao de respostas de IA. Porem, parte do arquivo ainda fala de Story Bible, enquanto o pipeline inicial de Story Bible foi removido. Isso pode ser legado util ou ruído historico, dependendo de quanto esse contrato ainda alimenta o Visual Bible/script fallback.

Recomendacao implementada:

- Separar `test_story_idea_normalization.py`.
- Separar `test_script_normalization.py`.
- Separar `test_storytelling_story_bible_compatibility.py`.
- Remover dois testes de validacao profunda do pipeline legado que nao tinham mais caminho direto no fluxo atual.
- Mover o fallback de roteiro baseado em payload antigo para `test_storytelling_script_normalization.py`.

Status implementado: Story Bible ficou como compatibilidade explicita, e nao como etapa ativa de pipeline.

### 4. Providers mock

Os providers mock aparecem em arquivos proprios e em testes de fallback. Como a aplicacao passou a bloquear mock em fluxos de producao, alguns testes podem parecer antigos. Ainda assim, mocks continuam uteis como doubles de teste e como contrato minimo.

Recomendacao implementada:

- Manter um smoke test por provider mock.
- Remover testes que validem detalhes internos sem impacto no produto.
- Garantir que testes de producao continuem bloqueando mock/free models.
- Nao remover mocks enquanto eles forem usados por testes de agente, retry ou jobs.

Status implementado: `test_mock_llm_provider.py`, `test_mock_image_provider.py`, `test_mock_speech_provider.py` e `test_mock_video_provider.py` ficaram com um teste cada.

### 5. Arquivos de um unico teste

Arquivos com apenas um teste nao sao necessariamente ruins, mas aqui alguns parecem bons candidatos a consolidacao.

Candidatos:

- `test_health.py` foi para `test_auth.py`.
- `test_director_agent.py` foi para `test_project_agent_routing.py`.
- `test_story_ideas_ordering.py` foi para `test_idea_lab.py`.
- `test_observability_middleware.py` pode continuar separado, porque middleware e um dominio proprio.

Status implementado: os tres primeiros foram consolidados; `test_observability_middleware.py` continua separado.

## Testes que nao recomendo remover

Mesmo que alguns parecam pequenos, eu nao removeria agora:

- Testes de seguranca e path traversal.
- Testes de uploads de PDF/DOCX/imagens.
- Testes de custos e limites.
- Testes de provider externo com timeout, retry e erro.
- Testes de idempotencia de video.
- Testes de deletar projetos em massa.
- Testes de normalizacao de JSON vindo de IA.
- Testes que garantem que mock nao entra em fluxo de producao.
- Testes de observabilidade, correlation id e eventos.

Esses testes sao baratos perto do dano de uma regressao nessas areas.

## Plano recomendado para enxugar com seguranca

### Fase 1: Reorganizacao sem remocao

Checklist:

- [x] Dividir `test_project_creation_flow.py` em arquivos menores por dominio.
- [x] Dividir `test_project_agent.py` por tipo de comportamento.
- [x] Dividir `test_storytelling_normalization_flow.py` em ideias, roteiro e compatibilidade de Story Bible.
- [x] Rodar coleta de testes apos a reorganizacao.
- [x] Confirmar que a reorganizacao nao reduziu a cobertura dos casos migrados.

Objetivo: melhorar manutencao sem reduzir cobertura.

### Fase 2: Consolidacao de arquivos pequenos

Checklist:

- [x] Mover `test_health.py` para `test_auth.py`.
- [x] Mover `test_story_ideas_ordering.py` para `test_idea_lab.py`.
- [x] Avaliar e mover `test_director_agent.py` para o grupo de agente de projeto.
- [x] Manter `test_observability_middleware.py` separado.
- [x] Rodar a suite completa.

Objetivo: reduzir dispersao sem apagar protecoes.

### Fase 3: Revisao de legado Story Bible

Checklist:

- [x] Mapear quais funcoes de Story Bible ainda sao chamadas pelo fluxo atual.
- [x] Separar testes que protegem contratos atuais de testes que apenas documentam historico.
- [x] Remover apenas testes sem caminho de execucao ou sem contrato publico.
- [x] Atualizar nomes para deixar claro o que e compatibilidade.
- [x] Rodar suite completa.

Objetivo: remover ruido historico sem quebrar fallback visual/script.

### Fase 4: Reducao dos mocks

Checklist:

- [x] Listar onde cada provider mock ainda e usado.
- [x] Manter um smoke test por provider mock.
- [x] Remover asserts sobre detalhes internos que nao afetam contrato.
- [x] Garantir cobertura de bloqueio de mock em producao.
- [x] Rodar testes de providers, agentes e producao.

Objetivo: manter mocks como ferramentas de teste, nao como produto paralelo.

### Fase 5: Marcacao por tipo de teste

Checklist:

- [x] Definir marcadores `unit`, `integration`, `provider`, `ui`, `security`.
- [x] Marcar testes mais lentos ou integrados.
- [x] Criar comandos documentados para rodar subconjuntos.
- [x] Ajustar CI para validar marcadores e manter suite completa em PR.

Objetivo: reduzir custo diario sem reduzir confianca.

## Ordem de prioridade

1. Dividir `test_project_creation_flow.py`.
2. Dividir `test_project_agent.py`.
3. Consolidar `test_health.py`, `test_story_ideas_ordering.py` e talvez `test_director_agent.py`.
4. Separar Story Bible legado de contratos atuais. Concluido.
5. Reduzir testes de providers mock. Concluido.
6. Adicionar marcadores de teste. Concluido.

## Resultado esperado

Depois da reorganizacao, a suite ainda deve ter aproximadamente a mesma cobertura, mas com menos atrito para manutencao. A reducao real de quantidade deve ser pequena no inicio. O maior ganho sera clareza:

- Menos arquivos gigantes.
- Menos testes legados misturados com fluxos atuais.
- Menos duplicidade em health/director/ordenacao.
- Mais facilidade para rodar subconjuntos relevantes.
- Mais seguranca para remover testes antigos depois de mapear uso real.

## Recomendacao final

Nao trate a suite como inchada por padrao. Ela cresceu porque o produto ganhou responsabilidades reais. A melhor estrategia e primeiro organizar e nomear melhor, depois remover com evidencia. Eu comecaria pela divisao dos arquivos grandes e so depois atacaria a reducao de quantidade.
