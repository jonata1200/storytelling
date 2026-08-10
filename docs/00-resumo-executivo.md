# Relatório de Análise da Aplicação — Storytelling Studio

> Data da análise: 10/08/2026
> Método: leitura do código-fonte, análise estática (ruff, mypy, vulture), execução da suíte de
> testes (60 arquivos, com PostgreSQL e Redis via Docker) e revisão manual dos fluxos principais
> (auth, jobs, geração, vídeo, finalização, UI NiceGUI).

## Visão geral

A aplicação está **funcional e bem estruturada em vários aspectos**:

- A suíte de testes passa integralmente (apenas ~5 testes pulados por serem smoke).
- Autenticação com cookies `HttpOnly`/`SameSite=Lax`/`Secure`, CSRF com HMAC, hash de senha
  PBKDF2-SHA256 e rate limit — qualidade acima da média para uma aplicação local.
- Erros de provider são tratados com fallback, redação de segredos em logs e mensagens amigáveis.
- Migrações Alembic em ordem (21 migrações) e modelos carregados corretamente no `env.py`.

Porém, a análise encontrou **problemas relevantes que explicam os bugs percebidos no uso**:

## Top 10 prioridades de correção

| # | Problema | Onde | Arquivo do relatório |
|---|----------|------|----------------------|
| 1 | **CI quebrado**: `mypy app tests` (27 erros) e `ruff check .` (1 erro) falham | `.github/workflows/ci.yml` | `03-erros-de-tipagem-e-lint.md`, `07-infraestrutura-e-ci.md` |
| 2 | **Duração escolhida no Idea Lab é ignorada** — sempre gera ideias de 5 minutos | `app/storytelling/idea_lab.py` | `02-bugs-funcionais.md` |
| 3 | **Contrato de resposta do chat do Diretor IA é frágil** — respostas em texto puro viram erro de JSON | `app/generation/director_agent.py`, `app/providers/llm/` | `01-bugs-criticos.md` |
| 4 | **Jobs em memória sem recuperação após reinício** — job PENDING pode ficar travado | `app/jobs/service.py`, `app/jobs/runner.py` | `01-bugs-criticos.md` |
| 5 | **"Limpar banco da aplicação" escondido na UI** (div `hidden`) | `app/ui/routes/settings_page.py` | `01-bugs-criticos.md` |
| 6 | **Código morto após `return`** no fluxo de aprovação de vídeo | `app/ui/visual/actions.py` | `02-bugs-funcionais.md`, `04-codigo-morto-e-legado.md` |
| 7 | **Estimativa de custo de vídeo não conta jobs re-executados** + laço duplicado | `app/video_generation/service.py` | `01-bugs-criticos.md`, `06-performance.md` |
| 8 | **Áudio de diálogo truncado silenciosamente** quando a fala passa do frame | `app/finalization/service.py` | `02-bugs-funcionais.md` |
| 9 | **Dois sistemas de autenticação** (`user_store.py` órfão) e código morto espalhado | `app/auth/user_store.py` e outros | `04-codigo-morto-e-legado.md`, `09-arquitetura-e-divida-tecnica.md` |
| 10 | **Funções duplicadas** (`render_timeline_video_with_audio`, `redact_secrets`) com risco de divergência | `app/finalization/`, `app/quality/security.py` | `04-codigo-morto-e-legado.md` |

## Como os arquivos estão organizados

| Arquivo | Conteúdo |
|---------|----------|
| `00-resumo-executivo.md` | Este resumo |
| `01-bugs-criticos.md` | Bugs com impacto direto no uso (falhas, travamentos, dados inconsistentes) |
| `02-bugs-funcionais.md` | Bugs de comportamento/lógica |
| `03-erros-de-tipagem-e-lint.md` | Erros de mypy e ruff (bloqueiam o CI) |
| `04-codigo-morto-e-legado.md` | Código morto, duplicado e resquícios de arquiteturas antigas |
| `05-seguranca.md` | Revisão de segurança |
| `06-performance.md` | Problemas de performance |
| `07-infraestrutura-e-ci.md` | Infraestrutura, configuração e CI |
| `08-teste-e-cobertura.md` | Qualidade da suíte de testes e lacunas |
| `09-arquitetura-e-divida-tecnica.md` | Dívida técnica e sugestões de arquitetura |

## Comandos usados na análise

```bash
.venv/Scripts/python.exe -m ruff check app        # 1 erro (I001)
.venv/Scripts/python.exe -m mypy app              # 11 erros em 7 arquivos
.venv/Scripts/python.exe -m mypy app tests        # 27 erros em 14 arquivos (igual ao CI)
.venv/Scripts/python.exe -m pytest tests -q       # ~540 testes, todos passando
.venv/Scripts/python.exe -m vulture app           # código morto
```
