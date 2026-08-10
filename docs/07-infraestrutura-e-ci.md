# Infraestrutura, Configuração e CI

---

## 7.1 CI está vermelho — nenhum push passa

**Arquivo:** `.github/workflows/ci.yml`

```yaml
- name: Lint
  run: ruff check .                    # 1 erro (I001) — falha
- name: Type check
  run: mypy app tests                  # 27 erros em 14 arquivos — falha
```

Nenhum dos dois passos passa hoje (ver `03-erros-de-tipagem-e-lint.md`). O CI está
efetivamente quebrado e não está protegendo o `main`.

**Ações:**
1. Corrigir os 27 erros de mypy e o de ruff, **ou**
2. Enquanto isso, rodar com `continue-on-error`/`--no-error-on-unused-ignores` para não
   bloquear, mas isso esconde o problema.

---

## 7.2 Variáveis de ambiente legadas no CI

`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` e `OPENROUTER_API_KEY` não existem mais no
código (não há Celery nem OpenRouter). Remover para não enganar quem configura o ambiente.

---

## 7.3 `pypdf` ausente das dependências

**Arquivo:** `app/storytelling/script_upload.py`

`_extract_pdf_with_pypdf` tenta `from pypdf import PdfReader` e, se não existir, cai no
parser regex (`_extract_pdf_text_fallback`), que extrai bem menos texto. **`pypdf` não está
em `requirements.lock`** nem no `pyproject.toml`, então a extração de PDF roda sempre no
modo degradado.

**Ação:** adicionar `pypdf` (ou `pypdfium2`) às dependências.

---

## 7.4 Porta padrão do PostgreSQL inconsistente

- `app/config/settings.py`: `DATABASE_URL = postgresql+asyncpg://...@localhost:5432/...`
- `docker-compose.yml`: porta exposta **5433:5432**
- `.env.example`: usa 5433

Sem `.env` (ou com `.env` desatualizado), a aplicação tenta conectar em `localhost:5432` e
falha. O `.env.example` corrige, mas o default do `settings.py` é uma armadilha.

**Ação:** alinhar o default de `settings.py` para 5433 ou padronizar o compose para 5432.

---

## 7.5 Versão mínima do NiceGUI desatualizada

`pyproject.toml`: `nicegui>=1.4.29` — mas `requirements.lock` fixa `nicegui==3.14.0`.
O código usa APIs recentes (ex.: `ui.upload(max_file_size=...)`, `response_timeout`,
`ui.dialog().props(...)`, dark theme). O piso de versão está muito abaixo e qualquer
instalação com `pip install -e . --no-deps` + resolução livre pode quebrar a UI.

**Ação:** atualizar o piso para a versão do lock (ex.: `nicegui>=3.14`).

---

## 7.6 Migrações Alembic — OK, mas sem checagem de drift

- 21 migrações em `alembic/versions/`, cabeça em `202608080021_project_model_settings.py`.
- `alembic/env.py` importa todos os modelos — correto.
- O CI roda apenas `alembic upgrade head`; **não** roda `alembic check` (autogenerate diff).

**Ação recomendada:** adicionar `alembic check` no CI para detectar modelos fora de sincronia.

---

## 7.7 Docker Compose — sem problemas críticos

`docker-compose.yml` sobe PostgreSQL (pgvector/pg16) e Redis 7 com healthchecks e volumes
persistentes. Nada a corrigir; nota: a porta do Postgres (5433) deveria ser a mesma do
default do `settings.py` (item 7.4).

---

## 7.8 Scripts PowerShell

- `scripts/story.ps1` é robusto (detecta Docker, aguarda healthcheck, gerencia migrações e
  background). Aprovado.
- `scripts/app.ps1`, `executar.ps1`, `finalizar.ps1` são wrappers de compatibilidade
  (conforme README).

---

## 7.9 `requirements.lock` vs `pyproject.toml`

- `requirements.lock` tem `playwright==1.61.0` (dev). OK.
- O `pyproject.toml` não lista `pypdf` (item 7.3) nem as versões reais de fastapi
  (0.139.2), nicegui (3.14.0) etc. — o lock é a fonte de verdade, mas o piso do pyproject
  está desatualizado (7.5).

---

## 7.10 Arquivos de runtime

- `.runtime/preferences.json` e `.runtime/users.json` — gitignored, bom.
- Permissões de arquivo em texto puro com chaves de API — ver `05-seguranca.md` item 5.2.7.
