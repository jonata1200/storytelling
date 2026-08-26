# Fase 02 — Meta para texto, roteiro e agentes

## Objetivo

Substituir Ollama Cloud por Meta no canal de texto sem alterar contratos narrativos, formatos JSON, versionamento ou comportamento de domínio.

Ao fim desta fase, Meta deve ser capaz de executar todas as tarefas de texto usadas pela aplicação.

## Escopo funcional

Meta deverá atender pelo menos:

- geração de ideias;
- geração de hooks;
- geração de roteiro;
- geração de cenas e shots;
- revisão de roteiro;
- extração de personagens e locais;
- prompts de storyboard, enquanto esse fluxo legado existir;
- chats/agentes de direção existentes.

## Arquivos sugeridos

```text
app/providers/llm/meta.py
app/providers/llm/types.py
app/providers/registry.py

app/config/settings.py
app/config/provider_policy.py

app/generation/service.py
app/generation/model_settings.py
app/visual_bible/script_profiles.py

tests/providers/test_meta_llm.py
tests/integration/test_meta_text_pipeline.py
```

## Estratégia de implementação

Preferir API oficial Meta Model API. Reutilizar, quando fizer sentido, a infraestrutura de cliente OpenAI-compatible já existente no projeto, mas expor uma implementação explicitamente chamada `MetaLLMProvider`.

O restante da aplicação não deve saber qual protocolo HTTP a Meta usa.

## Checklist — provider Meta

- [x] Criar `MetaLLMProvider`.
- [x] Implementar o protocolo `LLMProvider`.
- [x] Implementar autenticação oficial.
- [x] Implementar base URL configurável apenas quando necessário.
- [x] Implementar modelo padrão.
- [x] Implementar timeout.
- [x] Implementar retry somente para erros transitórios.
- [x] Implementar tratamento de 429.
- [x] Implementar tratamento de 5xx.
- [x] Não repetir automaticamente requisições em erros semânticos/4xx não transitórios.
- [x] Propagar correlation ID quando suportado.
- [x] Registrar provider/model na observabilidade.
- [x] Registrar uso/custo quando disponível.
- [x] Não logar prompt completo em nível inadequado quando houver conteúdo sensível.
- [x] Passar resultados pelo redaction existente antes de logs estruturados.

## Checklist — structured output

O projeto depende fortemente de JSON.

- [x] Validar saída JSON para `generate_story_ideas`.
- [x] Validar saída JSON para `generate_story_hooks`.
- [x] Validar saída JSON para `generate_script`.
- [x] Validar saída JSON para `generate_scenes_and_shots`.
- [x] Validar saída JSON para extração da Visual Bible.
- [x] Usar structured output/schema nativo da API se disponível e estável.
- [x] Caso contrário, preservar parser/normalização existente.
- [x] Preservar retry guidance atual.
- [x] Preservar normalizadores atuais.
- [x] Preservar fallbacks de domínio que ainda fizerem sentido.
- [x] Adicionar erro diagnóstico quando o modelo retornar JSON inválido repetidamente.

## Checklist — prompts existentes

- [x] Não reescrever todos os prompts nesta fase.
- [x] Rodar os templates atuais com Meta.
- [ ] Identificar templates com desempenho ruim.
- [x] Ajustar somente o necessário para aderência ao schema.
- [x] Preservar português brasileiro.
- [x] Preservar duração exata de cenas/shots.
- [x] Preservar regras de não usar narrador quando configuradas.
- [x] Preservar o contrato narrativo.
- [x] Preservar versão de `PromptTemplate`.
- [x] Registrar nova versão quando o texto do template mudar.

## Checklist — configurações por projeto

- [x] Permitir `provider=meta` em `ProjectModelSetting`.
- [ ] Definir modelos Meta válidos para tarefas de texto.
- [x] Remover dependência de modelo Ollama hard-coded.
- [x] Garantir que um projeto existente possa ser migrado para Meta sem recriação.
- [x] Criar função/migration de dados apenas se houver settings persistidos incompatíveis.
- [x] Atualizar UI de Configurações de IA para mostrar Meta.
- [x] Remover novos caminhos de UI que ofereçam Ollama como escolha; a remoção física do legado fica para a Fase 07.

## Checklist — smoke tests reais

- [ ] Smoke: ideia.
- [ ] Smoke: hook.
- [ ] Smoke: roteiro curto.
- [ ] Smoke: roteiro longo suportado.
- [ ] Smoke: cenas/shots.
- [ ] Smoke: extração de personagem/local.
- [ ] Smoke: timeout.
- [ ] Smoke: chave inválida.
- [ ] Smoke: rate limit simulado/real controlado.
- [ ] Medir duração média por tarefa.
- [ ] Medir taxa de JSON inválido.
- [ ] Registrar custo quando disponível.

## Testes automatizados

- [x] Provider contract test com respostas mockadas.
- [x] Teste de request body.
- [x] Teste de headers.
- [x] Teste de retry.
- [x] Teste de timeout.
- [x] Teste de 401/403.
- [x] Teste de 429.
- [x] Teste de 5xx.
- [x] Teste de JSON inválido.
- [ ] Teste de integração `idea → script → scenes`.
- [x] Teste de idempotência dos jobs narrativos.
- [x] Ruff.
- [x] mypy.
- [x] pytest.

## Critérios de aceite

- [x] `TEXT_PROVIDER=meta` executa todas as etapas textuais do projeto.
- [x] Nenhuma etapa textual precisa de Ollama para funcionar.
- [x] Os schemas/normalizadores existentes continuam válidos.
- [x] Observabilidade registra Meta corretamente.
- [x] Custos/usage não quebram quando o provider não retornar valor.
- [ ] Os smoke tests principais passam com a API real.
- [ ] É seguro marcar Ollama como "deprecated / pronto para remoção".
