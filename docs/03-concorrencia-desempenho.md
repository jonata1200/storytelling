# Concorrência e desempenho

## PERF-01 — FFmpeg bloqueia o event loop por até cinco minutos

**Severidade:** alta  
**Evidência:** `app/video_generation/finalization.py:215-220`

Uma função `async` chama `subprocess.run()` de modo síncrono, com timeout de 300 segundos. Durante
esse período o worker/event loop não consegue atender normalmente outras corrotinas.

**Impacto:** congelamento de requisições concorrentes, health checks, atualizações de progresso e
outras gerações; em produção pode provocar timeouts em cascata.

**Recomendação:** usar `asyncio.create_subprocess_exec()` ou executar o trabalho em thread/job
dedicado, mantendo cancelamento e timeout explícitos.

## PERF-02 — Vídeo final inteiro é carregado na memória

**Severidade:** média  
**Evidência:** `app/video_generation/finalization.py:248`

`read_bytes()` carrega todo o MP4 apenas para calcular metadados/hash posteriormente. Como os
assets gerados podem chegar a centenas de megabytes, cada finalização pode elevar fortemente o
RSS do processo e concorrer com outras gerações.

**Recomendação:** calcular hash em blocos e obter tamanho via `stat()`, sem materializar o arquivo
completo.

## CONC-01 — Callback captura variáveis mutáveis do laço

**Severidade:** média (risco latente)  
**Evidência:** `app/video_generation/continuous_review.py:319-329`; Ruff `B023`

`_adapted_video_cb` fecha sobre `idx` e `segment` sem fixá-los como argumentos padrão. No fluxo
atual ele aparenta ser consumido antes da próxima iteração, mas qualquer agendamento tardio ou
mudança para paralelismo fará o callback reportar o índice/segmento de outra iteração.

Além disso, os parâmetros recebidos `cur`, `tot` e `msg` são ignorados, escondendo o progresso
real produzido pela camada inferior.

**Recomendação:** vincular explicitamente índice e número do segmento na criação do callback e
definir se o progresso interno deve ser propagado.
