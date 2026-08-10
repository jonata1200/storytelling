# Bugs Funcionais

Bugs de comportamento/lógica que não derrubam a aplicação, mas produzem resultados
errados ou comportamento inesperado.

> **Status: 10/12 itens resolvidos** — atualizado em 10/08/2026 após a rodada de correções.
> Itens 2.2 e 2.3 foram resolvidos na rodada dos bugs críticos (itens 1.4 e 1.5).
> Item 2.9 confirmado como comportamento desejado pelo usuário.

---

## 2.1 Idea Lab ignora a duração escolhida (sempre 5 minutos) — ✅ CORRIGIDO

**Arquivo:** `app/storytelling/idea_lab.py`

**O que foi feito:**

- `build_idea_lab_prompt` agora usa `duration_minutes` (coagido com
  `coerce_duration_minutes`, faixa 5–25) em vez da constante `IDEA_LAB_DURATION_MINUTES`:
  `duration = f"{coerce_duration_minutes(duration_minutes):g}"`.
- O texto hardcoded "roteiro curto de 5 minutos" virou f-string interpolando `{duration}`.
- `generate_freeform_ideas` e `generate_freeform_idea_batches` agora derivam
  `duration = coerce_duration_minutes(target_duration_minutes)` (o parâmetro que vinha
  da UI em `home_pages.py` era descartado em toda a cadeia).
- `_normalize_idea` não sobrescreve mais `duration_minutes` com 5.0 — o valor passa a
  ser preservado via `normalize_story_idea_payload`, com o default coerente.
- A constante `IDEA_LAB_DURATION_MINUTES` permanece apenas como default dos parâmetros.

**Testes atualizados:** `tests/test_idea_lab.py` — o prompt com `duration_minutes=20`
agora contém "20 minutos"/"duration_minutes igual a 20"; geração com
`target_duration_minutes=6` retorna ideias de 6 min; persistência preserva a duração
da ideia (7.0 em vez de 5.0).

---

## 2.2 Custo de retentativa de vídeo fora do orçamento — ✅ CORRIGIDO (rodada de críticos)

**Arquivo:** `app/video_generation/service.py`

Resolvido na rodada anterior como item 1.4: o laço único de `_generate_video_clips_concurrent`
agora soma `frame.duration_seconds` de jobs `FAILED` que serão retentados, e o custo
estimado é calculado sobre `billable_seconds` que inclui essas retentativas.

---

## 2.3 Fala que excede o frame é cortada sem aviso — ✅ CORRIGIDO (rodada de críticos)

**Arquivo:** `app/finalization/service.py`

Resolvido na rodada anterior como item 1.5: `_add_dialogue_audio_items` agora emite
`logger.warning("dialogue_truncated ...")` e registra `truncated_ms` nas propriedades
do `TimelineItem` e nos detalhes do evento observável.

---

## 2.4 `_optional_provider` com parâmetro morto — ✅ CORRIGIDO

**Arquivo:** `app/config/settings.py`

O parâmetro `legacy_default` (que era ignorado com `_ = legacy_default`) foi removido
da assinatura, assim como os kwargs `legacy_default="google_ai"` nos callers de
`image_provider` e `video_provider`. O comportamento não muda: `effective_provider_for_channel`
já aplica o default `google_ai` para image/video quando o provider não está configurado.

---

## 2.5 `provider_requires_api_key` sempre retorna `True` — ✅ CORRIGIDO

**Arquivo:** `app/config/provider_policy.py`

A função agora distingue providers reais de mock/desconhecidos:

```python
def provider_requires_api_key(settings: Any, provider: str) -> bool:
    provider_name = str(provider or "").strip().casefold()
    if not provider_name or provider_name in MOCK_MODEL_IDS:
        return False
    return provider_name in SUPPORTED_AI_PROVIDERS or provider_name == "elevenlabs"
```

- `ollama_cloud`, `google_ai` e `elevenlabs` → `True`.
- Mock e providers desconhecidos/vazios → `False`.

**Teste adicionado:** `tests/test_provider_policy.py` —
`test_provider_requires_api_key_distinguishes_mock_and_unknown_providers`.

---

## 2.6 `get_or_create_prompt_template` quebra com task desconhecida — ✅ CORRIGIDO

**Arquivo:** `app/generation/service.py`

O acesso direto `DEFAULT_TEMPLATES[task]` foi substituído por `DEFAULT_TEMPLATES.get(task)`:

- Template persistido com task desconhecida: retorna o template existente sem tentar
  sobrescrever o texto (sem `KeyError`).
- Criação com task desconhecida: usa `"{prompt}"` como fallback de template (mesmo
  comportamento do `director_agent_chat`).

**Testes adicionados:** `tests/test_prompt_compiler.py` —
`test_get_or_create_prompt_template_creates_fallback_for_unknown_task` e
`test_get_or_create_prompt_template_keeps_persisted_unknown_task`.

---

## 2.7 Mensagem legada de Celery ainda tratada na UI — ✅ REMOVIDO (decisão do usuário)

**Arquivos:** `app/ui/page_runtime.py`, `app/ui/shared/assistant_state.py`

O usuário optou por **remover** a compatibilidade. Foram removidos:

- As constantes `LEGACY_EXTERNAL_QUEUE_MESSAGE` / `INTERNAL_QUEUE_MESSAGE`.
- A normalização da mensagem em `_project_ai_action` (page_runtime) e
  `_normalize_legacy_ai_message` (assistant_state) e seus usos em
  `load_assistant_messages`, `append_assistant_message_to_chat` e
  `sync_ai_action_events_to_chat`.

> Observação: mensagens legadas já persistidas no banco passarão a exibir o texto
> original ("Etapa enfileirada para execução pelo worker.") em vez do texto interno.
> Impacto cosmético em dados antigos.

---

## 2.8 `_positive_count` com tipagem frágil — ✅ CORRIGIDO

**Arquivo:** `app/ui/page_runtime.py`

Implementação mypy-safe com `isinstance` narrowing:

```python
def _positive_count(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        try:
            return int(value) > 0
        except ValueError:
            return False
    return False
```

Comportamento equivalente ao original para os valores reais (counts inteiros); corrige
os erros `No overload variant of "int"` e `Returning Any from function declared to
return "bool"`.

---

## 2.9 `save_script_from_ui` regenera cenas e planos sempre — ✅ CONFIRMADO (manter)

**Arquivo:** `app/ui/workspace/script_area.py`

O usuário confirmou que **quer manter a regeneração automática** de cenas e planos ao
salvar o roteiro pela UI. Nenhuma mudança de código. O custo de tokens é o preço da
consistência: storyboard/vídeo sempre refletem o roteiro editado.

---

## 2.10 Notificações de erro duplicadas por timestamp — ✅ CORRIGIDO

**Arquivo:** `app/ui/page_runtime.py` (`_notify_ai_action_failure_once`)

A chave de deduplicação não inclui mais `updated_at` (que mudava a cada poll e
re-notificava o mesmo erro):

```python
notification_key = f"{project_id}:{action}:{error}"
```

Agora a mesma falha (mesma ação + mesmo texto de erro) é notificada uma única vez.
O trade-off: uma falha genuinamente nova com texto idêntico à anterior não re-notifica
até a lista (cap 80) evoluir — aceitável, pois o card de status na UI também mostra o erro.

---

## 2.11 Exportação: manifest JSON tratado como sucesso silencioso — ✅ CORRIGIDO

**Arquivos:** `app/finalization/service.py`, `app/ui/workspace/storyboard_video_area.py`

A UI de finalização agora deixa o modo degradado explícito:

- Badge vermelho "manifest sem vídeo" quando `export.status == "MANIFEST_ONLY"`.
- Bloco de aviso explicando que nenhum vídeo foi gerado e que o arquivo é um manifest JSON.
- Botão de download renomeado para "Baixar manifest (JSON)".
- O `render_log` (motivo) continua visível no card.

---

## 2.12 `exports` sem clipe local: `MANIFEST_ONLY` silencioso — ✅ CORRIGIDO

Mesma correção do item 2.11 (a UI agora avisa explicitamente que a exportação ficou
**incompleta** quando `clip_paths` está vazio ou o FFmpeg não renderizou o MP4).
