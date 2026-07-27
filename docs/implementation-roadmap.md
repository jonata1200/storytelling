# Roadmap de Melhorias da Aplicacao

Este roadmap foi dividido em arquivos por fase para facilitar acompanhamento, implementacao incremental e validacao.

## Objetivos gerais

- Manter a aplicacao funcional para uso local enquanto prepara uma base segura para uso em rede ou producao.
- Reduzir risco de exposicao indevida de API, arquivos gerados e chaves de provedor.
- Tornar geracoes longas recuperaveis, observaveis e desacopladas do processo web.
- Fazer a qualidade tecnica refletir os comandos documentados: `ruff`, `pytest` e `mypy`.
- Melhorar previsibilidade de builds, custos, storage e operacao.

## Fases

1. [Fase 1 - Seguranca e fronteiras publicas](./roadmap-phase-01-security.md)
2. [Fase 2 - Jobs longos e pipeline recuperavel](./roadmap-phase-02-jobs.md)
3. [Fase 3 - Tipagem, organizacao da UI e qualidade estatica](./roadmap-phase-03-typing-ui.md)
4. [Fase 4 - Reprodutibilidade, CI e operacao](./roadmap-phase-04-ci-operations.md)
5. [Fase 5 - Storage, retencao e governanca de arquivos](./roadmap-phase-05-storage.md)
6. [Fase 6 - Custos, orcamentos e limites de uso](./roadmap-phase-06-costs.md)
7. [Fase 7 - Finalizacao de video e provider de voz](./roadmap-phase-07-finalization.md)
8. [Fase 8 - Observabilidade, auditoria e experiencia operacional](./roadmap-phase-08-observability.md)

## Ordem recomendada

1. Fase 1: seguranca e fronteiras publicas.
2. Fase 2: jobs longos e pipeline recuperavel.
3. Fase 3: tipagem e organizacao da UI.
4. Fase 4: reprodutibilidade e CI.
5. Fase 5: storage e retencao.
6. Fase 6: custos e limites.
7. Fase 7: finalizacao e voz.
8. Fase 8: observabilidade ampliada.

## Marcos sugeridos

### Marco A - Base segura local/producao

Inclui Fases 1 e 4. Ao final, a aplicacao tem comportamento documentado, CI minimo e fronteiras de seguranca por ambiente.

### Marco B - Pipeline robusto

Inclui Fases 2, 5 e 6. Ao final, jobs longos sao recuperaveis, custos sao controlados e storage tem governanca.

### Marco C - Manutencao e acabamento

Inclui Fases 3, 7 e 8. Ao final, a base fica mais facil de evoluir, o pipeline fecha melhor e a operacao ganha diagnostico.

## Checklist de validacao continua

- [ ] `ruff check .`
- [ ] `python -m pytest`
- [ ] `mypy app tests`
- [ ] `alembic upgrade head` em banco limpo
- [ ] Teste manual do fluxo principal:
  - [ ] criar projeto;
  - [ ] gerar roteiro;
  - [ ] gerar cenas e planos;
  - [ ] gerar visual bible;
  - [ ] aprovar prompts de storyboard;
  - [ ] gerar storyboards;
  - [ ] gerar clipes;
  - [ ] criar timeline;
  - [ ] exportar manifest ou MP4.

## Riscos a acompanhar

- Mudancas de autenticacao podem afetar a experiencia local se nao forem condicionadas por ambiente.
- Migrar jobs para Celery exige cuidado com sessoes de banco, idempotencia e feedback da UI.
- Refatorar UI grande sem testes de comportamento pode introduzir regressao visual.
- Remover mount de `/storage` pode quebrar URLs antigas se nao houver redirecionamento ou adaptacao na UI.
- Custos reais dependem de retorno e formato dos providers, que podem variar.
