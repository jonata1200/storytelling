# Relatorio da suite de testes

## Resumo executivo

A aplicacao tem uma suite grande, mas a maior parte dela ainda tem serventia. O volume atual e explicado pelo tipo de sistema: ha fluxos de IA, upload de arquivos, referencias visuais, geracao de roteiro, assets, video, custos, seguranca, storage, observabilidade e UI. Esses pontos sao propensos a regressao porque dependem de contratos estruturados, validacao de payloads, estados intermediarios e comportamento assicrono.

Inventario atual:

- 38 arquivos de teste.
- 306 testes coletados.
- Ultima validacao completa registrada no projeto: `306 passed`, com 1 aviso de deprecacao do Starlette/FastAPI TestClient.
- Arquivos mais pesados: `test_project_creation_flow.py`, `test_project_agent.py`, `test_storytelling_normalization_flow.py`, `test_visual_bible.py`, `test_visual_bible_script_profiles.py` e `test_openrouter_media_providers.py`.

Conclusao: nao recomendo remover testes em massa agora. Recomendo reorganizar, consolidar casos muito pequenos e revisar testes legados ligados ao antigo fluxo de Story Bible e aos providers mock. A suite pode ficar mais legivel e mais barata de manter sem perder a protecao que ela da hoje.

## Resposta direta

E necessario ter tantos testes?

Sim, em boa parte. O numero alto e justificavel porque a aplicacao tem muitos pontos sensiveis:

- Contratos de IA precisam aceitar saidas variaveis, incompletas ou malformadas.
- Uploads de PDF, DOCX e imagens precisam validar extensao, tamanho, path traversal e metadados.
- Fluxos de criacao de projeto mexem em estado, arquivos, jobs e interface.
- Seguranca, custos e storage sao areas onde regressao pequena pode ter impacto grande.
- Providers externos precisam de testes de erro, timeout, retry e fallback.

Existem testes antigos sem serventia?

Provavelmente existem alguns testes que podem ser fundidos, renomeados ou removidos depois de revisao. Os principais candidatos estao nas areas de Story Bible legado, providers mock e alguns testes muito pequenos de health/director/ordenacao. Mesmo assim, alguns desses testes ainda servem como protecao indireta para migracoes recentes, entao a remocao deve ser faseada.

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
- `test_storytelling_normalization_flow.py`, com revisao dos trechos legados
- `test_project_creation_flow.py`, com divisao por dominio
- `test_project_agent.py`, com divisao por dominio
- `test_project_bulk_delete.py`
- `test_video_retry.py`
- `test_video_durations.py`
- `test_storyboard_timeline.py`
- `test_finalization_profile.py`
- `test_observability_events.py`
- `test_observability_middleware.py`

### Manter, mas reorganizar

Esses testes parecem importantes, mas os arquivos estao grandes ou misturam responsabilidades:

- `test_project_creation_flow.py`
- `test_project_agent.py`
- `test_storytelling_normalization_flow.py`
- `test_visual_bible.py`
- `test_visual_bible_script_profiles.py`
- `test_openrouter_media_providers.py`
- `test_idea_lab.py`
- `test_initial_script_pipeline.py`

### Revisar antes de remover

Esses arquivos ou grupos podem conter testes antigos, redundantes ou de baixo valor isolado:

- `test_mock_llm_provider.py`
- `test_mock_image_provider.py`
- `test_mock_speech_provider.py`
- `test_mock_video_provider.py`
- `test_director_agent.py`
- `test_health.py`
- `test_story_ideas_ordering.py`
- Testes de Story Bible legado em `test_initial_script_pipeline.py`, `test_storytelling_normalization_flow.py` e `test_visual_bible.py`

## Analise por arquivo

| Arquivo | Testes | Linhas | Valor | Recomendacao |
| --- | ---: | ---: | --- | --- |
| `test_auth.py` | 4 | 61 | Alto | Manter. Cobre autenticacao e endpoints publicos/privados. Pode absorver `test_health.py`. |
| `test_costs.py` | 4 | 45 | Alto | Manter. Area financeira/custos e sensivel. |
| `test_dependencies.py` | 3 | 91 | Medio/alto | Manter. Ajuda a proteger grafo de dependencias entre artefatos. |
| `test_director_agent.py` | 1 | 22 | Medio/baixo | Revisar. Pode ser fundido em `test_project_agent.py` ou removido se o fluxo do director agent estiver coberto la. |
| `test_finalization_profile.py` | 6 | 91 | Alto | Manter. Fase recente e ligada a entrega final. |
| `test_health.py` | 1 | 10 | Baixo | Fundir em `test_auth.py`, pois ja ha cobertura de health live sem autenticacao. |
| `test_idea_lab.py` | 16 | 486 | Alto | Manter. Cobre laboratorio de ideias, validacao, filtros e persistencia. Pode receber o teste de ordenacao. |
| `test_initial_script_pipeline.py` | 5 | 282 | Medio/alto | Manter por enquanto. Revisar o teste legado que garante remocao do pipeline inicial de Story Bible. |
| `test_mock_image_provider.py` | 2 | 47 | Medio | Reduzir para contrato minimo ou mover para grupo de providers de teste. |
| `test_mock_llm_provider.py` | 4 | 112 | Medio | Revisar. Provider mock ainda e util para testes, mas nao deve ocupar muito espaco de produto. |
| `test_mock_speech_provider.py` | 1 | 25 | Medio | Manter como smoke test ou consolidar com outros mocks. |
| `test_mock_video_provider.py` | 2 | 34 | Medio | Manter como smoke test ou consolidar com outros mocks. |
| `test_observability_events.py` | 3 | 65 | Alto | Manter. Observabilidade foi fase recente e regressao aqui reduz visibilidade de falhas. |
| `test_observability_middleware.py` | 1 | 13 | Alto | Manter. Pequeno e protege correlation id. |
| `test_openrouter_media_providers.py` | 16 | 529 | Alto | Manter. Dividir em imagem e video se crescer mais. |
| `test_openrouter_provider.py` | 7 | 81 | Alto | Manter. Protege integracao de LLM e parametros de requisicao. |
| `test_production_settings.py` | 9 | 67 | Alto | Manter. Bloqueia mocks/free models e protege configuracao de producao. |
| `test_project_agent.py` | 20 | 1044 | Alto | Manter, mas dividir. Mistura roteamento, acoes, assets, qualidade, progresso e finalizacao. |
| `test_project_bulk_delete.py` | 8 | 221 | Alto | Manter. Delecao em massa e area destrutiva. |
| `test_project_creation_flow.py` | 46 | 1111 | Alto | Manter, mas dividir com prioridade. Arquivo virou concentrador de UI, storage, storyboard, assets e workspace. |
| `test_prompt_compiler.py` | 10 | 253 | Alto | Manter. Protege prompts, fallback e erros de provider. |
| `test_quality_continuity.py` | 3 | 45 | Alto | Manter. Pequeno e relevante para consistencia narrativa. |
| `test_quality_security.py` | 2 | 14 | Alto | Manter. Pequeno e sensivel. |
| `test_reference_upload.py` | 3 | 75 | Alto | Manter. Recurso recente de referencias visuais. |
| `test_script_upload.py` | 3 | 40 | Alto | Manter. Recurso recente de upload de PDF/DOCX. |
| `test_security_regressions.py` | 11 | 178 | Alto | Manter. Suite de regressao critica. |
| `test_settings.py` | 2 | 13 | Medio/alto | Manter. Pequeno e barato. |
| `test_speech_provider.py` | 1 | 52 | Medio | Manter se audio ainda faz parte do fluxo; caso contrario, marcar como legado. |
| `test_state_machine.py` | 2 | 14 | Alto | Manter. Pequeno e protege transicoes. |
| `test_storage_governance.py` | 4 | 100 | Alto | Manter. Storage e retencao sao areas de risco. |
| `test_story_ideas_ordering.py` | 1 | 31 | Medio/alto | Fundir em `test_idea_lab.py` ou em teste de servico de ideias. E recente e util. |
| `test_storyboard_timeline.py` | 15 | 476 | Alto | Manter. Protege storyboard e timeline. |
| `test_storytelling_normalization_flow.py` | 28 | 708 | Alto, com legado | Dividir por dominio. Revisar testes de Story Bible para separar contrato atual de comportamento legado. |
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

Status sugerido: manter todos os testes inicialmente, apenas mover.

### 2. `test_project_agent.py`

Tem alto valor, mas mistura decisoes do agente, acoes em lote, etapas, progresso, qualidade, assets e finalizacao. Isso dificulta saber se uma falha veio do roteamento do agente ou de um fluxo especifico.

Recomendacao:

- Separar testes de roteamento/conversa.
- Separar testes de execucao de acoes.
- Separar testes de progresso/estado.
- Separar testes de finalizacao/qualidade.

Status sugerido: manter todos, dividir em arquivos menores.

### 3. `test_storytelling_normalization_flow.py`

E importante porque protege normalizacao de respostas de IA. Porem, parte do arquivo ainda fala de Story Bible, enquanto o pipeline inicial de Story Bible foi removido. Isso pode ser legado util ou ruído historico, dependendo de quanto esse contrato ainda alimenta o Visual Bible/script fallback.

Recomendacao:

- Separar `test_story_idea_normalization.py`.
- Separar `test_script_normalization.py`.
- Separar `test_story_bible_legacy_contracts.py`.
- Depois revisar o arquivo legado e remover somente o que nao for consumido por nenhum fluxo atual.

Status sugerido: revisar antes de apagar.

### 4. Providers mock

Os providers mock aparecem em arquivos proprios e em testes de fallback. Como a aplicacao passou a bloquear mock em fluxos de producao, alguns testes podem parecer antigos. Ainda assim, mocks continuam uteis como doubles de teste e como contrato minimo.

Recomendacao:

- Manter um smoke test por provider mock.
- Remover testes que validem detalhes internos sem impacto no produto.
- Garantir que testes de producao continuem bloqueando mock/free models.
- Nao remover mocks enquanto eles forem usados por testes de agente, retry ou jobs.

Status sugerido: reduzir com cuidado.

### 5. Arquivos de um unico teste

Arquivos com apenas um teste nao sao necessariamente ruins, mas aqui alguns parecem bons candidatos a consolidacao.

Candidatos:

- `test_health.py` pode ir para `test_auth.py`.
- `test_director_agent.py` pode ir para `test_project_agent.py`.
- `test_story_ideas_ordering.py` pode ir para `test_idea_lab.py`.
- `test_observability_middleware.py` pode continuar separado, porque middleware e um dominio proprio.

Status sugerido: consolidar os tres primeiros se isso simplificar a navegacao.

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

- [ ] Dividir `test_project_creation_flow.py` em arquivos menores por dominio.
- [ ] Dividir `test_project_agent.py` por tipo de comportamento.
- [ ] Dividir `test_storytelling_normalization_flow.py` em ideias, roteiro e Story Bible legado.
- [ ] Rodar a suite completa apos cada divisao.
- [ ] Confirmar que a contagem de testes permanece igual.

Objetivo: melhorar manutencao sem reduzir cobertura.

### Fase 2: Consolidacao de arquivos pequenos

Checklist:

- [ ] Mover `test_health.py` para `test_auth.py`.
- [ ] Mover `test_story_ideas_ordering.py` para `test_idea_lab.py`.
- [ ] Avaliar se `test_director_agent.py` deve entrar em `test_project_agent.py`.
- [ ] Manter `test_observability_middleware.py` separado.
- [ ] Rodar a suite completa.

Objetivo: reduzir dispersao sem apagar protecoes.

### Fase 3: Revisao de legado Story Bible

Checklist:

- [ ] Mapear quais funcoes de Story Bible ainda sao chamadas pelo fluxo atual.
- [ ] Separar testes que protegem contratos atuais de testes que apenas documentam historico.
- [ ] Remover apenas testes sem caminho de execucao ou sem contrato publico.
- [ ] Atualizar nomes para deixar claro o que e legado.
- [ ] Rodar suite completa e fluxo manual de criacao de historia.

Objetivo: remover ruido historico sem quebrar fallback visual/script.

### Fase 4: Reducao dos mocks

Checklist:

- [ ] Listar onde cada provider mock ainda e usado.
- [ ] Manter um smoke test por provider mock.
- [ ] Remover asserts sobre detalhes internos que nao afetam contrato.
- [ ] Garantir cobertura de bloqueio de mock em producao.
- [ ] Rodar testes de providers, agentes e producao.

Objetivo: manter mocks como ferramentas de teste, nao como produto paralelo.

### Fase 5: Marcacao por tipo de teste

Checklist:

- [ ] Definir marcadores `unit`, `integration`, `provider`, `ui`, `security`.
- [ ] Marcar testes mais lentos ou integrados.
- [ ] Criar comandos documentados para rodar subconjuntos.
- [ ] Ajustar CI para rodar suite completa em PR e subconjuntos em desenvolvimento local.

Objetivo: reduzir custo diario sem reduzir confianca.

## Ordem de prioridade

1. Dividir `test_project_creation_flow.py`.
2. Dividir `test_project_agent.py`.
3. Consolidar `test_health.py`, `test_story_ideas_ordering.py` e talvez `test_director_agent.py`.
4. Separar Story Bible legado de contratos atuais.
5. Reduzir testes de providers mock.
6. Adicionar marcadores de teste.

## Resultado esperado

Depois da reorganizacao, a suite ainda deve ter aproximadamente a mesma cobertura, mas com menos atrito para manutencao. A reducao real de quantidade deve ser pequena no inicio. O maior ganho sera clareza:

- Menos arquivos gigantes.
- Menos testes legados misturados com fluxos atuais.
- Menos duplicidade em health/director/ordenacao.
- Mais facilidade para rodar subconjuntos relevantes.
- Mais seguranca para remover testes antigos depois de mapear uso real.

## Recomendacao final

Nao trate a suite como inchada por padrao. Ela cresceu porque o produto ganhou responsabilidades reais. A melhor estrategia e primeiro organizar e nomear melhor, depois remover com evidencia. Eu comecaria pela divisao dos arquivos grandes e so depois atacaria a reducao de quantidade.
