# Infraestrutura, Configuração e CI

> Status: **revisado em 10/08/2026** — todos os itens acionáveis foram corrigidos.

---

## 7.1 CI está vermelho — nenhum push passa

**Status: ✅ RESOLVIDO** (pelas correções de `03-erros-de-tipagem-e-lint.md`)

- `ruff check .` → `All checks passed!` ✅
- `mypy app tests` → `Success: no issues found in 280 source files` ✅
- `pip check` → `No broken requirements found.` ✅
- `pytest --collect-only -q -m "unit or integration or provider or ui or security"` → ✅
- Suíte completa `pytest -m "not smoke"` → ✅ passando (1 skip esperado)

O CI voltou a proteger o `main`.

---

## 7.2 Variáveis de ambiente legadas no CI

**Status: ✅ JÁ RESOLVIDO** (remoção ocorreu na rodada de código morto, `04/4.1`)

Busca completa em `.github/workflows/ci.yml`, `scripts/*.ps1`, `README.md`, `.env.example`,
`alembic.ini`, `docker-compose.yml` e `app/` **não encontra mais** `CELERY_BROKER_URL`,
`CELERY_RESULT_BACKEND` nem `OPENROUTER_API_KEY`. Restam apenas artefatos `.pyc` órfãos
em `__pycache__` de provedores `openrouter` já removidos (sem efeito em runtime).

---

## 7.3 `pypdf` ausente das dependências

**Status: ✅ RESOLVIDO**

- `pyproject.toml` → adicionado `"pypdf>=6.15.0"` (em ordem alfabética)
- `requirements.lock` → adicionado `pypdf==6.15.0` (entre `Pygments` e `pytest`; BOM e
  CRLF preservados, diff de 1 linha)
- Instalado no ambiente de dev; `pip check` limpo

A extração de PDFs agora roda com o parser completo (`PdfReader`). O fallback regex
(`_extract_pdf_text_fallback`) permanece para PDFs degenerados: o teste
`test_extract_script_text_from_textual_pdf_fallback` continua exercitando o fallback
(verificado — o `pypdf` lança `PdfReadError` no PDF sintético do teste, caindo no fallback).
O `try/except ModuleNotFoundError` foi mantido como proteção defensiva.

---

## 7.4 Porta padrão do PostgreSQL inconsistente

**Status: ✅ RESOLVIDO**

`app/config/settings.py` — default de `DATABASE_URL` alterado de
`localhost:5432` → `localhost:5433`, alinhado ao `docker-compose.yml`
(`${POSTGRES_PORT:-5433}:5432`) e ao `.env.example` (5433).

O CI não é afetado (define `DATABASE_URL` explicitamente com 5432 no serviço do job).

---

## 7.5 Versão mínima do NiceGUI desatualizada

**Status: ✅ RESOLVIDO**

`pyproject.toml` — `nicegui>=1.4.29` → `nicegui>=3.14.0` (piso alinhado ao lock `3.14.0`).

---

## 7.6 Migrações Alembic — OK, mas sem checagem de drift

**Status: ✅ RESOLVIDO**

- Adicionado passo `Check for model/migration drift` ao `.github/workflows/ci.yml`,
  executando `alembic check` logo após `alembic upgrade head`.
- Análise estática prévia: nenhum `models.py` mudou desde a última migração
  (cabeça `202608080021_project_model_settings.py`, commit de 2026-08-08) e não há
  mudanças não commitadas. Os enums nativos PG foram autogerados das mesmas metadata;
  `compare_type` não está habilitado no `env.py` (comparação mais leniente).
- ⚠️ Não foi possível validar localmente (sem Docker/Postgres nesta máquina). O primeiro
  push do CI é o validador real. Se o `alembic check` acusar drift, o procedimento é
  gerar uma migração com `alembic revision --autogenerate` e revisá-la.

---

## 7.7 Docker Compose — sem problemas críticos

**Status: ✅ SEM AÇÃO NECESSÁRIA**

Nota do relatório (porta 5433 vs default do settings) foi resolvida pelo item 7.4.

---

## 7.8 Scripts PowerShell

**Status: ✅ SEM AÇÃO NECESSÁRIA** — aprovado (robusto, gerencia Docker, healthcheck,
migrações e background).

---

## 7.9 `requirements.lock` vs `pyproject.toml`

**Status: ✅ RESOLVIDO (parcialmente coberto)**

- `pypdf` adicionado (item 7.3) ✅
- Piso do NiceGUI atualizado (item 7.5) ✅
- Piso do `fastapi` também atualizado: `>=0.111.0` → `>=0.139.0` (lock `0.139.2`) ✅
- Demais pisos (alembic, pydantic, sqlalchemy, etc.) ficam abaixo do lock, o que é
  intencional: o lock é a fonte de verdade para instalações reprodutíveis, e pisos
  permissivos permitem upgrades — desde que a CI (instalando a partir do lock) valide.

---

## 7.10 Arquivos de runtime

**Status: ✅ SEM AÇÃO NECESSÁRIA** — gitignored; permissões tratadas em `05-seguranca.md` (5.2.7).
