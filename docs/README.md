# Auditoria técnica do projeto Storytelling

Data da auditoria: 23/08/2026

## Escopo e método

Foi revisado todo o código Python em `app/`, as migrações Alembic, scripts, configuração,
documentação e testes. A auditoria combinou leitura estática, busca de padrões de risco,
compilação, Ruff, mypy e execução integral da suíte.

Resultados automatizados:

- `pytest`: **429 aprovados, 1 ignorado**;
- `mypy app`: **sem erros em 191 arquivos**;
- `compileall app`: **sucesso**;
- `ruff check app tests`: **27 ocorrências**.

Os testes verdes não invalidam os achados: vários estão em caminhos de produção, concorrência,
configuração e desempenho que não são exercitados pela suíte.

## Relatórios por categoria

- [Erros funcionais](01-erros-funcionais.md)
- [Segurança](02-seguranca.md)
- [Concorrência e desempenho](03-concorrencia-desempenho.md)
- [Configuração e implantação](04-configuracao-implantacao.md)
- [Qualidade e manutenção](05-qualidade-manutencao.md)
- [Lacunas de testes](06-lacunas-de-testes.md)
- [Remoção da geração de imagens por IA](07-remocao-geracao-imagens.md)

## Resumo de prioridade

| Prioridade | Quantidade | Principais temas |
|---|---:|---|
| Alta | 3 | UI sem autenticação, finalização incompleta, bloqueio do event loop |
| Média | 5 | configuração ignorada, detalhe interno em resposta, callback frágil, memória e modularidade |
| Baixa | 2 grupos | lint e dívida de legibilidade |

Nenhum arquivo de código foi alterado por esta auditoria.

## Situação após a correção

As correções foram aplicadas em 23/08/2026:

- FUN-01 e FUN-02 corrigidos;
- SEC-01, SEC-02 e SEC-03 corrigidos;
- PERF-01, PERF-02 e CONC-01 corrigidos;
- CFG-01 e CFG-02 corrigidos;
- QUAL-01 corrigido, com Ruff sem ocorrências;
- testes de regressão adicionados para finalização, configuração, UI e bind de rede.

CFG-03 permanece como recomendação operacional: fixar imagens por digest exige uma política de
atualização de dependências e escolha explícita dos digests aprovados. QUAL-02 e QUAL-03 são
refatorações arquiteturais de longo alcance, não defeitos isolados; devem ser executadas em
entregas próprias para não introduzir regressões nos fluxos atualmente cobertos.
