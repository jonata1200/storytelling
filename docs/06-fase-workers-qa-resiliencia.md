# Fase 06 — Workers, QA, resiliência e interface

## Objetivo

Tornar o pipeline Meta + Vibes confiável para tarefas longas, browser automation, múltiplos shots e falhas externas, preservando o `GenerationJob` existente como fonte de verdade.

## Estado da implementação (2026-08-27)

Implementação de aplicação concluída e validada para fila Redis Streams, worker separado,
heartbeat/reclaim, locks e concorrência, retomada por external ID, cancelamento/retry,
QA multimodal Meta, regeneração limitada, review humano, UI de status/QA e observabilidade.

Bloqueio operacional restante: o adapter concreto de browser do Vibes depende de uma sessão
autorizada e dos seletores da interface disponibilizada à conta. O projeto mantém a porta
`VibesBrowserBackend`, perfil/lock dedicados e falha segura, sem incorporar cookies, credenciais
ou endpoints privados. A fase só deve ser declarada encerrada em produção depois de instalar esse
adapter autorizado e executar o smoke test real do provider.

Validação local: `pytest`, `ruff check .`, `mypy app` e `docker compose config --quiet` aprovados.

## Princípio

Texto rápido pode continuar no executor interno enquanto fizer sentido.

Browser automation e vídeo devem rodar fora do processo web principal.

## Arquitetura alvo

```text
FastAPI / NiceGUI
       ↓
PostgreSQL ← fonte de verdade
       ↓
Redis
       ↓
Worker
  ├── Meta Image
  └── Vibes Video
```

## Checklist — modelo de jobs

- [ ] Reutilizar `GenerationJob`.
- [ ] Adicionar tipos de job necessários para image/video/ingredient/QA.
- [ ] Reutilizar `external_job_id`.
- [ ] Reutilizar `attempts`.
- [ ] Reutilizar `max_attempts`.
- [ ] Reutilizar `idempotency_key`.
- [ ] Reutilizar `request_payload`.
- [ ] Reutilizar `response_payload`.
- [ ] Reutilizar `cost_estimate`.
- [ ] Reutilizar observabilidade.
- [ ] Não criar um segundo banco de jobs dentro do worker.

## Checklist — fila/worker

- [ ] Definir protocolo de enqueue no Redis.
- [ ] Criar processo worker separado.
- [ ] Criar comando de inicialização do worker.
- [ ] Adicionar worker ao `docker-compose.yml` apenas se fizer sentido para o ambiente local.
- [ ] Implementar graceful shutdown.
- [ ] Implementar heartbeat.
- [ ] Implementar reclaim de job abandonado.
- [ ] Implementar lock por browser profile.
- [ ] Implementar limite de concorrência Vibes.
- [ ] Implementar limite de concorrência Meta Image.
- [ ] Respeitar rate limits.
- [ ] Não manter browser dentro do processo FastAPI.

## Checklist — idempotência

- [ ] `generate visual reference` idempotente.
- [ ] `sync ingredient` idempotente.
- [ ] `generate shot` idempotente por tentativa explícita.
- [ ] Download idempotente.
- [ ] Finalização idempotente.
- [ ] Extração de frame idempotente.
- [ ] Retry não pode criar dois assets marcados como a mesma variante sem rastreio.
- [ ] Persistir external IDs antes de polling longo sempre que possível.

## Checklist — recuperação

- [ ] Recuperar job PENDING antigo.
- [ ] Recuperar job RUNNING cujo worker morreu.
- [ ] Detectar browser session perdida.
- [ ] Detectar arquivo parcial.
- [ ] Detectar download concluído antes de crash.
- [ ] Continuar polling sem submeter nova geração quando external job id já existe.
- [ ] Permitir retry manual.
- [ ] Permitir cancelamento local.
- [ ] Registrar quando cancelamento remoto não é possível.

## Checklist — QA automático

Começar simples. Não bloquear a produção com um sistema de visão complexo logo no início.

- [ ] Criar `QAResult`.
- [ ] Extrair frames-chave do vídeo.
- [ ] Usar Meta multimodal para comparar vídeo/frames com `ShotGenerationSpec`.
- [ ] Avaliar presença dos personagens.
- [ ] Avaliar local.
- [ ] Avaliar roupa/estado.
- [ ] Avaliar prop crítico.
- [ ] Avaliar ação principal.
- [ ] Avaliar violações claras de continuidade.
- [ ] Gerar score por dimensão.
- [ ] Gerar score total.
- [ ] Gerar motivos.
- [ ] Não auto-rejeitar em score limítrofe no primeiro release.
- [ ] Auto-rejeitar apenas falhas objetivas configuradas.
- [ ] Encaminhar casos incertos para review humano.

## Checklist — política de regeneração

- [ ] Definir limite automático de tentativas por Shot.
- [ ] Não criar loop infinito de regeneração.
- [ ] Transformar erro de QA em instrução de correção.
- [ ] Preservar prompt original.
- [ ] Preservar prompt da tentativa.
- [ ] Preservar motivo de rejeição.
- [ ] Preservar custo.
- [ ] Permitir usuário desligar auto-regeneration.
- [ ] Parar e pedir review humano ao atingir limite.

## Checklist — UI de produção

Fluxo recomendado:

```text
História
Personagens
Locais
Roteiro
Cenas / Shots
Biblioteca Visual
Produção de Vídeo
Review
Finalização
```

- [ ] Mostrar status por Shot.
- [ ] Mostrar thumbnail/frame.
- [ ] Mostrar referências usadas.
- [ ] Mostrar status do Vibes.
- [ ] Mostrar QA score.
- [ ] Mostrar custo.
- [ ] Mostrar tentativa atual.
- [ ] Botão gerar.
- [ ] Botão regenerar.
- [ ] Botão aprovar.
- [ ] Botão rejeitar.
- [ ] Botão cancelar.
- [ ] Exibir erro amigável.
- [ ] Disponibilizar detalhes técnicos em seção avançada.
- [ ] Não mostrar secret/cookie/token.
- [ ] Atualizar progresso sem bloquear a página.

## Checklist — observabilidade

- [ ] Evento de submit.
- [ ] Evento de polling.
- [ ] Evento de download.
- [ ] Evento de finalização.
- [ ] Evento de sync ingredient.
- [ ] Evento de QA.
- [ ] Evento de reject/regenerate.
- [ ] Correlation ID.
- [ ] project_id.
- [ ] shot_id.
- [ ] generation_job_id.
- [ ] provider.
- [ ] model quando aplicável.
- [ ] tempo por etapa.
- [ ] custo estimado/reportado.
- [ ] error class.
- [ ] Nunca logar secret.

## Testes

- [ ] Worker process test.
- [ ] Redis enqueue/dequeue.
- [ ] Lock do browser profile.
- [ ] Reclaim de job.
- [ ] Idempotência após crash.
- [ ] QA mockado.
- [ ] Retry policy.
- [ ] Auto-regeneration limit.
- [ ] UI status.
- [ ] Cancelamento.
- [ ] Segurança de secrets.
- [ ] Teste de duas gerações concorrentes.
- [ ] Ruff.
- [ ] mypy.
- [ ] pytest.

## Critérios de aceite

- [ ] Fechar/reiniciar FastAPI não perde um job externo já submetido.
- [ ] Browser automation não executa dentro do processo web.
- [ ] Não há duplicação silenciosa em retries.
- [ ] O usuário consegue acompanhar cada Shot.
- [ ] Existe review humano.
- [ ] Existe QA automático inicial sem criar loops infinitos.
- [ ] Logs permitem diagnosticar uma falha sem expor credenciais.
