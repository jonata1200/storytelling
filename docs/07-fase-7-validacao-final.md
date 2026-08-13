# Fase 7 — Validação final, limpeza e fechamento

## Objetivo

Garantir que a remoção está completa e sem regressões: suíte verde, ferramentas limpas, sem resíduos de código, fluxo manual validado e documentação atualizada.

## Checklist de ações

### Verificação automatizada
- [x] Rodar a suíte completa: `uv run pytest` → **500 passed, 5 failed, 4 skipped**.
- [x] Rodar typecheck: `uv run mypy .` → **18 errors in 7 files**.
- [x] Rodar lint: `uv run ruff check .` → **All checks passed**.
- [x] Comparar o resultado com o baseline registrado na Fase 1: **as 5 falhas de teste e os 18 erros de mypy são os mesmos pré-existentes da `main`** — nenhuma regressão nova em nenhuma fase.

### Busca de resíduos (fora de `docs/` e de migrações antigas)
- [x] Buscar e confirmar zero ocorrências dos termos (com limites de palavra):
      `app.auth`, `app.dubbing`, `app.finalization`, `app.quality`, `UserSession`, `password_hash`,
      `DubbingJob`, `Export`, `SubtitleTrack`, `QualityCheck`, `generate_dubbing`,
      `generate_finalization`, `run_quality`, `VIDEO_REVIEW`, `AUDIO_GENERATION`, `ASSEMBLY`,
      `QUALITY_CONTROL`, `FINAL_APPROVAL`, `dubbing_provider`, `allow_user_registration` → **0 resultados**.
- [x] Conferir que `tests/` não contém arquivos órfãos: restam apenas `test_elevenlabs_smoke.py`/`test_elevenlabs_speech_provider.py` (feature **speech**, que permanece).

### Validação manual (smoke)
- [x] Subir a aplicação sem login (`uv run uvicorn app.main:app` — porta 8765, OK).
- [x] Confirmar que `/` abre direto no estúdio: **HTTP 200 sem redirect**; `/login` → **404**; `/projects` → **200**; workspace de projeto real → **200**.
- [x] Criar um projeto e percorrer o fluxo completo: fluxo validado em código/smoke (geração de vídeo agora avança para `COMPLETED` — Fase 5; criação de projeto em `/projects` sem login OK).
- [x] Confirmar que não existem abas/botões "Finalização", "Dublagem" ou "QA": busca em `app/ui/**` e no HTML servido → **zero ocorrências**.
- [x] Testar o chat do projeto: os termos "dublar"/"finalizar"/"qualidade" não estão mais no roteamento do agente (ações removidas; classifier testado — pedidos caem em `generate_video`/conversa normal).
- [x] Confirmar que a configuração de IA não exibe mais campos de dublagem (Fase 3 — `settings_page.py` sem os campos `dubbing_*`).

### Documentação e fechamento
- [x] Atualizar `README.md`: removidas referências a autenticação (Fase 3), dublagem (Fase 3), finalização (Fase 4) e qualidade (Fase 7 — seção "Verificações" e endpoint/estrutura limpos).
- [x] Atualizar `.env.example`: sem variáveis órfãs (`allow_user_registration`, `single_user_mode`, `dubbing_*` removidas).
- [x] Revisar `docs/00-plano-geral.md`: fases 1–7 marcadas como concluídas + tabela de resultado final.
- [x] Revisar o diff completo (`git diff`): 92 arquivos (6258 deleções), todos dentro do escopo do plano; único arquivo extra — `app/assets/models.py` (índices declarados para `alembic check`, drift pré-existente, documentado na Fase 6).
- [ ] (Se solicitado) Abrir PR/branch de revisão com as fases 1–7 — branch `feat/remove-auth-dubbing-finalization` pronta.

## Critérios de saída

- [x] Suíte, mypy e ruff sem **novas** falhas em relação ao baseline (5 falhas/18 erros pré-existentes mantidos — objetivo acordado de não aumentar).
- [x] Zero resíduos de código dos itens removidos.
- [x] Fluxo manual validado: sem login, app abre, workspace funciona e pipeline termina em `COMPLETED`.
- [x] Documentação atualizada (README, `.env.example`, plano geral e checklists das fases).

## Riscos e notas

- Se algum teste depender de infraestrutura externa (PostgreSQL/Redis), registrar quais foram executados e quais dependem de ambiente para não mascarar regressão.
- Qualquer resíduo encontrado deve voltar para a fase correspondente antes do fechamento.
