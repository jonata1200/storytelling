# Erros de Tipagem e Lint

Resultados exatos das ferramentas na data da análise. **Estes erros quebravam o CI**
(`.github/workflows/ci.yml` roda `mypy app tests` e `ruff check .` em todo push).

> **Status: ✅ TODOS OS ERROS CORRIGIDOS (10/08/2026)**
> `mypy app` → 0 erros · `mypy tests` → 0 erros · `ruff check app tests` → limpo.
> O CI está destravado para os comandos `mypy app tests` e `ruff check .`.

---

## 3.1 Ruff — 1 erro ✅

Comando: `.venv/Scripts/python.exe -m ruff check .`

```text
I001 [*] Import block is un-sorted or un-formatted
 --> app/ui/shared/generation_progress.py:1:1
Found 1 error. [*] 1 fixable with the `--fix` option.
```

**Correção aplicada:** reordenados os imports em `app/ui/shared/generation_progress.py`
(`import logging` antes dos `from ... import ...`). `ruff check app tests` → **limpo**.

---

## 3.2 Mypy na aplicação — 11 erros em 7 arquivos ✅

Comando: `.venv/Scripts/python.exe -m mypy app` → **0 erros** (antes: 11 em 7 arquivos).

```text
app\storyboards\prompts.py:181: error: "Base" has no attribute "id"  [attr-defined]      ✅
app\config\api_keys.py:59: error: Unused "type: ignore" comment  [unused-ignore]         ✅
app\visual_bible\reference_status.py:134: error: "Base" has no attribute "id"  ✅
app\visual_bible\service.py:200: error: Value of type "object" is not indexable  [index] ✅
app\visual_bible\service.py:202: error: Value of type "object" is not indexable  [index] ✅
app\generation\project_agent.py:477: error: Need type annotation for "generated_frames"  ✅
app\generation\project_agent.py:493: error: Incompatible types in assignment ...          ✅
app\generation\project_agent.py:530: error: Function is missing a return type annotation ✅
app\ui\workspace\script_area.py:333: error: Argument 2 to "_schedule_missing_scenes_generation"
                                                   has incompatible type "Any | None"; expected "UUID"  ✅
app\ui\page_runtime.py:105: error: Returning Any from function declared to return "bool"   ✅
app\ui\page_runtime.py:105: error: No overload variant of "int" matches argument type "object" ✅
```

### Correções aplicadas

| Local | Causa | Correção |
|-------|-------|----------|
| `storyboards/prompts.py:181`, `visual_bible/reference_status.py:134` | `select(model)` com modelo dinâmico (união `Character \| Location \| Prop`) faz o plugin do SQLAlchemy resolver `scalars()` para `Base`, que não declara `id` | `cast(Character \| Location \| Prop, item/target)` no laço antes de acessar `.id` |
| `config/api_keys.py:59` | `# type: ignore[arg-type]` sem efeito (config tem `warn_unused_ignores = true`) | Comentário removido |
| `visual_bible/service.py:200,202` | `row[1]` em lista concatenada `[*a, *b, *c, *d]` de `Row` heterogêneos → mypy une para `object` | Compreensão aninhada `for rows in (a, b, c, d) for row in rows` preserva a ordem e mantém cada `Row` indexável |
| `project_agent.py:477,493` | `generated_frames = []` sem anotação e atribuição de `list[StoryboardFrame] \| None` | `generated_frames: list[StoryboardFrame] = []` + variável intermediária `frames` com o `None`-check antes da atribuição |
| `project_agent.py:530` | `_storyboard_frame_progress` sem anotação de retorno | `-> StoryboardProgressCallback \| None` (importado de `app.storyboards.service`) |
| `script_area.py:333` | `script_id` (`Any \| None`) não estreita dentro de lambda capturada | Variável tipada `scene_script_id: UUID = script_id` criada fora da lambda |
| `page_runtime.py:105` | `int(value or 0)` com `value: object` | ✅ Corrigido na rodada de bugs funcionais (item 2.8) |

---

## 3.3 Mypy nos testes — 16 erros adicionais ✅

Comando: `.venv/Scripts/python.exe -m mypy app tests` → **0 erros** (antes: 27 erros em 14 arquivos,
sendo 11 da aplicação + 16 de testes).

| Teste | Erro | Correção |
|-------|------|----------|
| `test_visual_bible_script_profiles.py:179,191` | `list[object]` vs `list[dict[Any, Any]]` em `_merge_profile_items` | Dados anotados como `list[dict]` |
| `test_auth.py:385,386` | `memoryview[int]` de `bytes \| memoryview[int]` não tem `.decode` | `bytes(response.body).decode()` |
| `test_api_keys.py:26` | `dict[str, object]` vs `dict[str, str \| None]` no `.update` | `values: dict[str, object]` |
| `test_api_keys.py:84` | Parâmetros de fixture sem anotação (`disallow_untyped_defs`) | `monkeypatch: pytest.MonkeyPatch`, `tmp_path: Path` (+ imports) |
| `test_projects_service.py:16` | Retorno de `Any` de função declarada `object \| None` (`warn_return_any`) | `cast(object, ...)` |
| `test_projects_service.py:72-75` | `session.added[0]` era `object` | `self.added: list[Any]` |
| `test_project_bulk_delete.py:84,139,178` | `list.extend` usado como valor (`... or len(...)`) | Helper `_record_deleted_storage_uris` |
| `test_google_ai_video_provider.py:54`, `test_google_ai_image_provider.py:40` | `hdrs={}` inferido como `dict[Never, Never]` vs `Message[str, str]` | `hdrs=Message()` (padrão já usado em `test_openai_compatible_llm_provider.py`) |

---

## 3.4 Configuração das ferramentas

- `pyproject.toml` habilita `ruff` (E, F, I, UP, B, ASYNC) e `mypy` com
  `disallow_untyped_defs`/`check_untyped_defs` — as regras agora **são cumpridas**.
- **Próxima recomendação (fora do escopo desta rodada):** adicionar `ruff` e `mypy` como
  `pre-commit` hooks para evitar regressões nos próximos pushes.
