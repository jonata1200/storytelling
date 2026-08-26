# Lacunas de testes

A suíte atual é ampla e passou integralmente, mas os seguintes comportamentos relevantes não
impediram os defeitos encontrados.

## TEST-01 — Finalização parcial

Não há teste que crie mais de três segmentos, deixe parte deles pendente e confirme que a
finalização é recusada. Esse cenário detectaria `FUN-01`.

## TEST-02 — Diretório de trabalho e URI relativo

Falta executar a finalização com storage relativo e CWD diferente, confirmando que todos os
caminhos passam pelo resolvedor canônico. Esse cenário detectaria `FUN-02`.

## TEST-03 — Autenticação da UI em ambiente não local

Os testes de autenticação cobrem a API, mas não demonstram que `/`, `/projects/*`, `/ideas` e
`/settings` sejam bloqueados em produção. Esse teste deve validar a superfície NiceGUI completa.

## TEST-04 — Responsividade durante FFmpeg

Não existe teste de concorrência que mantenha uma finalização em andamento e verifique se um
health check ou outra requisição continua respondendo. Ele evidenciaria o bloqueio do event loop.

## TEST-05 — Variáveis de ambiente anunciadas

Faltam testes que configurem `OPENROUTER_IMAGE_BASE_URL` e `OPENROUTER_IMAGE_MODEL` via ambiente e
validem a requisição resultante. Atualmente esses valores são silenciosamente ignorados.

## TEST-06 — Lint como porta de qualidade

Como o Ruff retorna erro enquanto a suíte é considerada saudável, o lint aparentemente não está
sendo aplicado como etapa obrigatória de CI. Recomenda-se executar ao menos `ruff check`, `mypy`
e `pytest` como gates separados.
