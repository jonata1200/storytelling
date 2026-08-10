# Bugs Funcionais

Bugs de comportamento/lógica que não derrubam a aplicação, mas produzem resultados
errados ou comportamento inesperado.

---

## 2.1 Idea Lab ignora a duração escolhida (sempre 5 minutos)

**Arquivo:** `app/storytelling/idea_lab.py`

- `build_idea_lab_prompt(..., duration_minutes, ...)` (linha ~37) recebe `duration_minutes`
  mas usa a constante `IDEA_LAB_DURATION_MINUTES = 5.0` no texto do prompt
  (`duration = f"{IDEA_LAB_DURATION_MINUTES:g}"`).
- `generate_freeform_ideas(..., target_duration_minutes=5.0)` (linha ~108) e
  `generate_freeform_idea_batches(...)` (linha ~132) também ignoram o parâmetro
  (`duration = IDEA_LAB_DURATION_MINUTES`).
- `_normalize_idea` (linha ~244) sobrescreve `normalized["duration_minutes"]` com 5.0.

A UI (`app/ui/routes/home_pages.py` ~linha 795) passa
`target_duration_minutes=coerce_duration_minutes(...)` — o valor do usuário é **descartado**
em toda a cadeia. As ideias sempre dizem 5 minutos e o prompt pede 5 minutos, mesmo quando o
usuário escolheu outra duração.

**Correção sugerida:** usar o parâmetro `duration_minutes` em `build_idea_lab_prompt` e
propagar `target_duration_minutes` para `duration` nos dois geradores (removendo a constante
hardcoded do fluxo).

---

## 2.2 Custo de retentativa de vídeo fora do orçamento

Ver `01-bugs-criticos.md` item 1.4 — o primeiro laço de `_generate_video_clips_concurrent`
não soma `frame.duration_seconds` de jobs `FAILED` que serão retentados no segundo laço.

---

## 2.3 Fala que excede o frame é cortada sem aviso

Ver `01-bugs-criticos.md` item 1.5 (`app/finalization/service.py`).

---

## 2.4 `_optional_provider` com parâmetro morto

**Arquivo:** `app/config/settings.py` (`_optional_provider`, linhas ~113-124)

```python
legacy_default: str = "ollama_cloud",
...
_ = legacy_default
```

O parâmetro `legacy_default` é ignorado. O código sugere que havia a intenção de usar um
default legado para `image_provider`/`video_provider`, mas hoje o comportamento é:
`effective_provider_for_channel` já aplica o default `google_ai` para image/video quando o
provider não está configurado. Manter os dois caminhos é confuso.

---

## 2.5 `provider_requires_api_key` sempre retorna `True`

**Arquivo:** `app/config/provider_policy.py` (linhas ~88-92)

```python
def provider_requires_api_key(settings: Any, provider: str) -> bool:
    if provider == "ollama_cloud":
        return True
    if provider == "google_ai":
        return True
    return True
```

Os ramos são inúteis — a função equivale a `return True`. Se no futuro algum provider não
exigir chave, o código não foi preparado.

---

## 2.6 `get_or_create_prompt_template` quebra com task desconhecida

**Arquivo:** `app/generation/service.py` (linha ~415)

```python
template.template_text = DEFAULT_TEMPLATES[task]   # KeyError se task não existir
```

Se um `PromptTemplate` persistido tiver `task` fora de `DEFAULT_TEMPLATES` (ex.: template
criado por versão antiga), `KeyError`. Para uma aplicação local é improvável, mas o acesso
direto ao dict sem `.get()` é frágil.

---

## 2.7 Mensagem legada de Celery ainda tratada na UI

**Arquivo:** `app/ui/page_runtime.py`

```python
LEGACY_EXTERNAL_QUEUE_MESSAGE = "Etapa enfileirada para execução pelo " + "w" + "orker."
```

A aplicação não tem mais Celery (o README afirma isso), mas a UI ainda normaliza a mensagem
legada do worker. É compatibilidade defensiva — pode ser removida junto da limpeza geral
(ver `04-codigo-morto-e-legado.md`).

---

## 2.8 `_positive_count` com tipagem frágil

**Arquivo:** `app/ui/page_runtime.py` (linha ~105)

```python
try:
    return int(value or 0) > 0
except (TypeError, ValueError):
    return False
```

Funciona em runtime, mas o mypy não consegue estreitar o tipo de `value: object` (gera os
erros `No overload variant of "int"` e `Returning Any from function declared to return
"bool"`). Ver `03-erros-de-tipagem-e-lint.md`.

---

## 2.9 `save_script_from_ui` regenera cenas e planos sempre

**Arquivo:** `app/ui/workspace/script_area.py` (linhas ~60-141)

Ao salvar o roteiro pela UI, `_refresh_script_derivatives_from_ui` roda
`regenerate_scenes_and_shots` — o que apaga e recria cenas/planos derivados a cada edição
de texto, mesmo para correções de digitação. Com `mark_downstream_stale=False` o
versionamento é preservado, mas a regra é agressiva e custa tokens de IA. Sugere-se
confirmar o comportamento desejado (editar roteiro recria cenas automaticamente?).

---

## 2.10 Notificações de erro duplicadas por timestamp

**Arquivo:** `app/ui/page_runtime.py` (`_notify_ai_action_failure_once`)

A chave de deduplicação usa `updated_at` + `error`. Se o erro se repetir com o mesmo texto,
mas `updated_at` mudar a cada poll, o usuário pode receber popups repetidos. A intenção
("notificar uma vez por ocorrência") é razoável, mas o critério por timestamp é frágil.

---

## 2.11 Exportação: manifest JSON tratado como sucesso silencioso

**Arquivo:** `app/finalization/service.py` (`export_timeline`, ~linhas 680-830)

Quando o FFmpeg não existe ou a renderização falha, a função escreve um **manifest JSON**
como "exportação" (`status = "MANIFEST_ONLY"`) e o fluxo segue normalmente
(`advance_project_status(project, ProjectStatus.FINAL_APPROVAL)`). O usuário pode achar que
tem um vídeo final quando na verdade tem um JSON. A UI/qualidade precisam deixar explícito
o modo degradado (o `render_log` traz o motivo, mas o card pode não mostrar).

---

## 2.12 `exports` sem clipe local: `MANIFEST_ONLY` silencioso

Mesmo arquivo/análise do item 2.11: `clip_paths` vazio → manifest JSON. Para um estúdio de
vídeo, exportar um JSON quando não há clipes é questionável; ao menos o usuário deve ser
avisado de que a exportação ficou **incompleta**.
