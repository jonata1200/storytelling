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

- [ ] Criar `MetaLLMProvider`.
- [ ] Implementar o protocolo `LLMProvider`.
- [ ] Implementar autenticação oficial.
- [ ] Implementar base URL configurável apenas quando necessário.
- [ ] Implementar modelo padrão.
- [ ] Implementar timeout.
- [ ] Implementar retry somente para erros transitórios.
- [ ] Implementar tratamento de 429.
- [ ] Implementar tratamento de 5xx.
- [ ] Não repetir automaticamente requisições em erros semânticos/4xx não transitórios.
- [ ] Propagar correlation ID quando suportado.
- [ ] Registrar provider/model na observabilidade.
- [ ] Registrar uso/custo quando disponível.
- [ ] Não logar prompt completo em nível inadequado quando houver conteúdo sensível.
- [ ] Passar resultados pelo redaction existente antes de logs estruturados.

## Checklist — structured output

O projeto depende fortemente de JSON.

- [ ] Validar saída JSON para `generate_story_ideas`.
- [ ] Validar saída JSON para `generate_story_hooks`.
- [ ] Validar saída JSON para `generate_script`.
- [ ] Validar saída JSON para `generate_scenes_and_shots`.
- [ ] Validar saída JSON para extração da Visual Bible.
- [ ] Usar structured output/schema nativo da API se disponível e estável.
- [ ] Caso contrário, preservar parser/normalização existente.
- [ ] Preservar retry guidance atual.
- [ ] Preservar normalizadores atuais.
- [ ] Preservar fallbacks de domínio que ainda fizerem sentido.
- [ ] Adicionar erro diagnóstico quando o modelo retornar JSON inválido repetidamente.

## Checklist — prompts existentes

- [ ] Não reescrever todos os prompts nesta fase.
- [ ] Rodar os templates atuais com Meta.
- [ ] Identificar templates com desempenho ruim.
- [ ] Ajustar somente o necessário para aderência ao schema.
- [ ] Preservar português brasileiro.
- [ ] Preservar duração exata de cenas/shots.
- [ ] Preservar regras de não usar narrador quando configuradas.
- [ ] Preservar o contrato narrativo.
- [ ] Preservar versão de `PromptTemplate`.
- [ ] Registrar nova versão quando o texto do template mudar.

## Checklist — configurações por projeto

- [ ] Permitir `provider=meta` em `ProjectModelSetting`.
- [ ] Definir modelos Meta válidos para tarefas de texto.
- [ ] Remover dependência de modelo Ollama hard-coded.
- [ ] Garantir que um projeto existente possa ser migrado para Meta sem recriação.
- [ ] Criar função/migration de dados apenas se houver settings persistidos incompatíveis.
- [ ] Atualizar UI de Configurações de IA para mostrar Meta.
- [ ] Remover novos caminhos de UI que ofereçam Ollama como escolha; a remoção física do legado fica para a Fase 07.

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

- [ ] Provider contract test com respostas mockadas.
- [ ] Teste de request body.
- [ ] Teste de headers.
- [ ] Teste de retry.
- [ ] Teste de timeout.
- [ ] Teste de 401/403.
- [ ] Teste de 429.
- [ ] Teste de 5xx.
- [ ] Teste de JSON inválido.
- [ ] Teste de integração `idea → script → scenes`.
- [ ] Teste de idempotência dos jobs narrativos.
- [ ] Ruff.
- [ ] mypy.
- [ ] pytest.

## Critérios de aceite

- [ ] `TEXT_PROVIDER=meta` executa todas as etapas textuais do projeto.
- [ ] Nenhuma etapa textual precisa de Ollama para funcionar.
- [ ] Os schemas/normalizadores existentes continuam válidos.
- [ ] Observabilidade registra Meta corretamente.
- [ ] Custos/usage não quebram quando o provider não retornar valor.
- [ ] Os smoke tests principais passam com a API real.
- [ ] É seguro marcar Ollama como "deprecated / pronto para remoção".
