# Qualidade e manutenção

## QUAL-01 — O lint oficial falha com 27 ocorrências

**Severidade:** baixa isoladamente; média como sinal de regressão de qualidade

`ruff check app tests` encontrou:

- 6 blocos de imports fora do padrão (`I001`);
- 8 imports não usados (`F401`);
- 4 variáveis locais não usadas (`F841`);
- 7 linhas acima do limite (`E501`);
- 2 capturas inseguras de variável de laço (`B023`);

Locais com maior relevância:

- `app/video_generation/continuous_review.py:327-329` — `B023`, com risco funcional;
- `app/ui/workspace/asset_cards.py:52,88` — código morto;
- `app/ui/workspace/rules.py:67` — regra calcula `assets_ready` e não usa o resultado;
- `app/ui/workspace/video_area.py:240` — condição calculada e ignorada;
- `app/providers/image/openrouter.py:14` — configuração importada e ignorada.

Os demais apontamentos são de formatação/imports em módulos de providers, vídeo, visual bible e
um helper de testes. O relatório bruto pode ser reproduzido com o comando acima.

## QUAL-02 — Módulos excessivamente grandes concentram responsabilidades

**Severidade:** média

Exemplos:

- `app/video_generation/continuous.py`: aproximadamente 56 KB;
- `app/video_generation/continuous_planning.py`: aproximadamente 35 KB;
- `app/storytelling/service.py`: aproximadamente 34 KB;
- `app/ui/workspace/video_area.py`: aproximadamente 31 KB;
- `app/generation/service.py`: aproximadamente 31 KB.

Esses arquivos misturam orquestração, persistência, regras, transformação e apresentação. Isso
aumenta o raio de impacto de mudanças e dificulta testar falhas isoladas, especialmente nos
fluxos de vídeo.

**Recomendação:** separar por caso de uso e fronteira (planejamento, persistência, provider,
progresso e apresentação), preservando APIs públicas durante a refatoração.

## QUAL-03 — Exceções amplas escondem causas específicas

**Severidade:** baixa a média

Há dezenas de `except Exception` no código de UI e orquestração. Vários convertem qualquer falha
em notificação genérica. Isso pode tratar erros de programação como falhas operacionais e tornar
regressões difíceis de detectar.

**Recomendação:** capturar exceções esperadas na fronteira correspondente e deixar defeitos
inesperados chegarem ao logger/handler central com stack trace e correlation ID.
