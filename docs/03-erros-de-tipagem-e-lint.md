# Erros de Tipagem e Lint

Resultados exatos das ferramentas na data da análise. **Estes erros quebram o CI**
(`.github/workflows/ci.yml` roda `mypy app tests` e `ruff check .` em todo push).

---

## 3.1 Ruff — 1 erro

Comando: `.venv/Scripts/python.exe -m ruff check .`

```text
I001 [*] Import block is un-sorted or un-formatted
 --> app/ui/shared/generation_progress.py:1:1
Found 1 error. [*] 1 fixable with the `--fix` option.
```

**Correção:** `ruff check app/ui/shared/generation_progress.py --fix`.

---

## 3.2 Mypy na aplicação — 11 erros em 7 arquivos

Comando: `.venv/Scripts/python.exe -m mypy app`

```text
app\storyboards\prompts.py:181: error: "Base" has no attribute "id"  [attr-defined]
app\config\api_keys.py:59: error: Unused "type: ignore" comment  [unused-ignore]
app\visual_bible\reference_status.py:134: error: "Base" has no attribute "id"  [attr-defined]
app\visual_bible\service.py:200: error: Value of type "object" is not indexable  [index]
app\visual_bible\service.py:202: error: Value of type "object" is not indexable  [index]
app\generation\project_agent.py:477: error: Need type annotation for "generated_frames"
app\generation\project_agent.py:493: error: Incompatible types in assignment ...
app\generation\project_agent.py:530: error: Function is missing a return type annotation
app\ui\workspace\script_area.py:333: error: Argument 2 to "_schedule_missing_scenes_generation"
                                                   has incompatible type "Any | None"; expected "UUID"
app\ui\page_runtime.py:105: error: Returning Any from function declared to return "bool"
app\ui\page_runtime.py:105: error: No overload variant of "int" matches argument type "object"
```

### Observações por erro

| Local | Causa provável | Correção |
|-------|----------------|----------|
| `storyboards/prompts.py:181`, `visual_bible/reference_status.py:134` | `select(model.id)` onde `model` está anotado como `Base` | Tipar os argumentos com `type[UUIDPrimaryKeyMixin]` ou `Protocol` com `id` |
| `config/api_keys.py:59` | `# type: ignore[arg-type]` sem efeito | Remover o comentário ou corrigir o tipo |
| `visual_bible/service.py:200,202` | indexar valor tipado como `object` | Ajustar a anotação/`cast` |
| `project_agent.py:477,493` | `generated_frames` sem anotação e atribuição com tipo incompatível (`list[Any]` vs `list[StoryboardFrame] \| None`) | Anotar `generated_frames: list[StoryboardFrame]` |
| `project_agent.py:530` | `_storyboard_frame_progress` sem anotação de retorno | Adicionar tipo de retorno |
| `script_area.py:333` | `script_id` não estreita dentro da lambda (`Any \| None`) | Fazer o narrowing fora da lambda |
| `page_runtime.py:105` | `int(value or 0)` com `value: object` | `int(str(value or 0))` com try/except ou `operator` |

---

## 3.3 Mypy nos testes — 16 erros adicionais

Comando: `.venv/Scripts/python.exe -m mypy app tests` → **27 erros em 14 arquivos**
(11 da aplicação acima + 16 de testes).

Exemplos dos erros em testes:

```text
tests\test_visual_bible_script_profiles.py:179: error: Argument 3 to "_merge_profile_items" has
    incompatible type "list[object]"; expected "list[dict[Any, Any]]"  [arg-type]
tests\test_visual_bible_script_profiles.py:191: error: (idem)
tests\test_auth.py:385: error: Item "memoryview[int]" of "bytes | memoryview[int]" has no attribute "decode"
tests\test_auth.py:386: error: Item "memoryview[int]" of "bytes | memoryview[int]" has no attribute "decode"
```

**Correção geral:** rodar `mypy app tests` até 0 erros. Isso destrava o CI. Se a intenção é
não bloquear o CI por erros de teste, ao menos fixar `app` e mover os erros de `tests` para
um `# mypy: ignore-errors` ou per-file-ignores no `pyproject.toml`.

---

## 3.4 Configuração das ferramentas

- `pyproject.toml` habilita `ruff` (E, F, I, UP, B, ASYNC) e `mypy` com
  `disallow_untyped_defs`/`check_untyped_defs` — as regras são coerentes, mas não estão
  sendo cumpridas (erros acima).
- **Recomendação:** adicionar `ruff` e `mypy` como `pre-commit` hooks ou fazer o CI rodar
  com `--no-fail-on-errors` temporariamente enquanto os erros são corrigidos, para não
  deixar o CI permanentemente vermelho.
