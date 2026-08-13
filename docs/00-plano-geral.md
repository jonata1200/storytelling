# Plano: Remoção da autenticação, dublagem e finalização

## Objetivo

Reduzir o escopo da aplicação removendo três blocos de funcionalidade:

1. **Sistema de autenticação completo** (login, registro, sessões, CSRF, middleware de UI).
2. **Etapa de dublagem** da geração de vídeo (integrada ao ElevenLabs).
3. **Etapa de finalização** da geração de vídeo (timeline final, export FFmpeg e legendas).

Além disso, conforme decisão registrada abaixo, o pipeline de vídeo passa a **terminar imediatamente após a geração dos clipes** — sem revisão separada e sem etapa de qualidade.

## Decisões tomadas (registradas com o solicitante)

| # | Decisão | Escolha |
|---|---------|---------|
| D1 | Destino dos dados das tabelas órfãs (`users`, `user_sessions`, `dubbing_jobs`, `exports`, `subtitle_tracks` e colunas `owner_user_id`/`reviewer_user_id`) | **Remover tabelas e colunas via migrações Alembic** (banco fica limpo; dados existentes são perdidos) |
| D2 | Como termina o pipeline de geração de vídeo | **Encerrar direto após gerar os clipes**: o projeto é considerado concluído quando os clipes de vídeo são gerados. Remove-se também a revisão separada (VIDEO_REVIEW) e a etapa de qualidade |

## Escopo

### Será removido

- Módulo `app/auth/` (rotas, serviço, sessão, senhas, CSRF, middleware de UI).
- Modelos `User`, `UserSession` e colunas de FK que apontavam para `users.id`
  (`workspaces.owner_user_id`, `approvals.reviewer_user_id`, `clip_reviews.reviewer_user_id`).
- Dependência `require_authenticated_user` em todas as rotas da API.
- Módulo `app/dubbing/` e provider `app/providers/dubbing/`.
- Módulo `app/finalization/` (timeline final, export, legendas, ffmpeg_exporter).
- Módulo `app/quality/` (etapa de controle de qualidade, continuidade e QA de segurança).
- Etapas de job `dubbing`, `finalization` e `quality` (`ProjectStep`).
- Estados de projeto `VIDEO_REVIEW`, `AUDIO_GENERATION`, `ASSEMBLY`, `QUALITY_CONTROL`, `FINAL_APPROVAL`.
- Ações do agente de chat `generate_dubbing`, `generate_finalization`, `run_quality`.
- Abas da UI "Finalização" e "Dublagem" e a etapa "QA" do fluxo de produção.
- Configurações: `allow_user_registration`, `single_user_mode`, `dubbing_*`.
- Tabelas/colunas órfãs no banco (ver Fase 6).

### Será mantido (cuidado para não remover por engano)

- `Timeline`/`TimelineItem` do módulo `storyboards` — usados pelo animatic/storyboard e pela UI de timeline preliminar.
- `ffmpeg_path` e o componente de readiness do FFmpeg na observabilidade.
- `app_secret_key` — ainda usado pelo `storage_secret` do NiceGUI e pela assinatura de preferências.
- Preferências de perfil `user_display_name`, `user_email`, `user_avatar_path`, `user_theme` (são preferências de UI, não autenticação).
- Speech de personagens (vozes) — é separado da dublagem e permanece.
- Migrações Alembic antigas — permanecem no histórico; as novas migrações fazem o drop.

## Fases e ordem de execução

| Fase | Arquivo | Conteúdo | Status |
|------|---------|----------|--------|
| 1 | [`01-fase-1-preparacao.md`](01-fase-1-preparacao.md) | Preparação e baseline (testes, branch, confirmação) | ✅ Concluída |
| 2 | [`02-fase-2-remocao-autenticacao.md`](02-fase-2-remocao-autenticacao.md) | Remoção do sistema de autenticação | ✅ Concluída |
| 3 | [`03-fase-3-remocao-dublagem.md`](03-fase-3-remocao-dublagem.md) | Remoção da dublagem | ✅ Concluída |
| 4 | [`04-fase-4-remocao-finalizacao.md`](04-fase-4-remocao-finalizacao.md) | Remoção da finalização | ✅ Concluída |
| 5 | [`05-fase-5-ajuste-pipeline-video.md`](05-fase-5-ajuste-pipeline-video.md) | Ajuste do pipeline de vídeo e estados (fim do fluxo + qualidade) | ✅ Concluída |
| 6 | [`06-fase-6-migracoes-banco.md`](06-fase-6-migracoes-banco.md) | Migrações de banco de dados (drops) | ✅ Concluída |
| 7 | [`07-fase-7-validacao-final.md`](07-fase-7-validacao-final.md) | Validação final, limpeza e fechamento | ✅ Concluída |

## Resultado final

| Verificação | Baseline (Fase 1) | Final (Fase 7) |
|-------------|-------------------|----------------|
| `uv run pytest` | 551 passed, 5 failed, 5 skipped | **500 passed**, 5 failed (as mesmas pré-existentes), 4 skipped |
| `uv run mypy .` | 18 errors in 7 files | **18 errors in 7 files** (mesmos pré-existentes) |
| `uv run ruff check .` | All checks passed | **All checks passed** |
| Resíduos de código | — | **0** (busca com limites de palavra) |
| `alembic check` | — | **No new upgrade operations detected** |
| Smoke sem login | — | `/` 200 (sem redirect), `/login` 404, `/projects` 200, workspace 200 |

> As 5 falhas de teste e os 18 erros de mypy são **pré-existentes na `main`** (ver Fase 1): durante todo o plano eles permaneceram idênticos, sem nenhuma regressão nova. O objetivo acordado era **não aumentar** esses números — cumprido.

## Regras de execução

> Todas as fases foram executadas na branch `feat/remove-auth-dubbing-finalization`. Migração aplicada no banco de desenvolvimento (`202608130026`).

- **Ordem importa**: as fases 2–5 removem código; a fase 6 remove as tabelas **depois** que o código deixou de referenciá-las. Não antecipar os drops.
- **Testes por fase**: ao final de cada fase, a suíte deve rodar sem erros (testes que referenciam o que foi removido são atualizados ou excluídos na própria fase).
- **Sem resíduos**: cada fase termina com uma busca de resíduos dos termos removidos (o checklist da fase inclui os termos a pesquisar).
- **Não alterar migrações antigas**: as migrações já aplicadas ficam como estão; a Fase 6 adiciona migração(ões) novas.

## Critérios globais de aceite

1. A aplicação inicia sem depender de tabelas removidas e sem exigir login.
2. Fluxo completo funciona: briefing → roteiro → biblioteca visual → storyboard → vídeo → projeto **concluído**.
3. Nenhuma referência a `app.auth`, `app.dubbing`, `app.finalization`, `app.quality`, `DubbingJob`, `Export`, `UserSession`, `generate_dubbing`, `generate_finalization` ou `run_quality` fora de `docs/` e de migrações antigas.
4. Suíte de testes, mypy e ruff verdes (Fase 7).
5. Banco limpo: tabelas e colunas órfãs removidas (Fase 6).
